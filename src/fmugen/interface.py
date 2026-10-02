"""Infer a fmugen.toml from an ordinary Python model.

`infer_config()` imports the model, inspects the entry function or class and makes
one probe call with the start values to discover what it returns or which
attributes it sets. The result is a config dict (the same shape as fmugen.toml)
plus comments explaining each guess; `render_toml()` writes it out for the user to
review. `fmugen build model.py` runs the same inference in memory.
"""
import ast
import enum
import importlib
import importlib.util
import inspect
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path

from fmugen.config import InterfaceError

TIME_NAMES = {"dt": "step_size", "step_size": "step_size", "h": "step_size", "t": "time", "time": "time"}
CALL_NAMES = ("step", "do_step", "update", "__call__")
PROBE_STEP_SIZE = 1.0
SCALARS = (bool, int, float, str)


def load_module(model_path):
    model_path = Path(model_path).resolve()
    if str(model_path.parent) not in sys.path:
        sys.path.insert(0, str(model_path.parent))
    spec = importlib.util.spec_from_file_location(model_path.stem, model_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[model_path.stem] = module
    spec.loader.exec_module(module)
    return module


def parse_target(target):
    """'path/model.py[:Name]' or 'package.module:Name' -> (path or None, module name or None, Name or None)."""
    target = str(target)
    path, sep, name = target.rpartition(":")
    if not sep or not name.isidentifier() or (not path.endswith(".py") and "/" in name):
        path, name = target, None
    if path.endswith(".py"):
        return Path(path), None, name
    if name is None:
        raise InterfaceError(f"{target!r}: give a .py file, or 'package.module:Name' for an installed module")
    return None, path, name


def infer_config(target, call=None, config_dir=None):
    """Return (config dict, {(section, name): comment}) for a model target."""
    path, module_name, name = parse_target(target)
    module = load_module(path) if path else importlib.import_module(module_name)
    entry = _pick_entry(module, name)
    config_dir = Path(config_dir or (path.parent if path else ".")).resolve()

    if path:
        rel = Path(path).resolve().relative_to(config_dir).as_posix()
        entry_ref = f"{rel}:{entry.__name__}"
    else:
        entry_ref = f"{module_name}:{entry.__name__}"

    data = {"model": {"entry": entry_ref}}
    if path:
        sources = _local_sources(Path(path).resolve(), config_dir)
        if sources:
            data["model"]["sources"] = sources
    comments = {}
    if inspect.isclass(entry):
        _infer_class(entry, call, data, comments)
    else:
        if call:
            raise InterfaceError("--call only applies to classes")
        _infer_function(entry, data, comments)
    return data, comments


def _local_sources(entry_file, config_dir):
    """Files and directories under config_dir that the model imported (besides the entry file).

    A module inside a subdirectory contributes the whole top-level directory, so packages
    and flat sibling imports are copied together.
    """
    sources = set()
    for module in list(sys.modules.values()):
        file = getattr(module, "__file__", None)
        if not file:
            continue
        file = Path(file).resolve()
        if not file.is_relative_to(config_dir) or "site-packages" in file.parts or file == entry_file:
            continue
        rel = file.relative_to(config_dir)
        sources.add(rel.parts[0] if len(rel.parts) > 1 else rel.as_posix())
    entry_rel = entry_file.relative_to(config_dir)
    if len(entry_rel.parts) > 1:
        sources.add(entry_rel.parts[0])
    return sorted(sources)


def _pick_entry(module, name):
    if name:
        if not hasattr(module, name):
            raise InterfaceError(f"{module.__name__} has no {name!r}")
        return getattr(module, name)
    own = [
        obj for attr, obj in vars(module).items()
        if not attr.startswith("_")
        and (inspect.isfunction(obj) or inspect.isclass(obj))
        and getattr(obj, "__module__", None) == module.__name__
        and not (inspect.isclass(obj) and issubclass(obj, (enum.Enum, BaseException)))
    ]
    if len(own) != 1:
        found = ", ".join(o.__name__ for o in own) or "none"
        raise InterfaceError(
            f"cannot tell which function or class is the model (found: {found}); "
            f"use {module.__name__}.py:Name"
        )
    return own[0]


# ---------------- functions ----------------

def _infer_function(fn, data, comments):
    _arguments(fn, "inputs", data, comments)
    kwargs = {**_probe_kwargs(data, ("inputs",)), **_time_kwargs(data.get("time", {}))}
    try:
        result = fn(**kwargs)
    except Exception as e:
        comments[("outputs", None)] = f"probe call failed ({e!r}); add the outputs by hand"
        return
    _outputs_from_return(result, data, comments, default_name="y", is_class=False)
    _detect_states(data, comments, returned=result if isinstance(result, Mapping) else None, obj=None)


# ---------------- classes ----------------

def _infer_class(cls, call, data, comments):
    _arguments(cls.__init__, "parameters", data, comments, skip_self=True, allow_time=False)

    method_name = call or _pick_method(cls)
    if method_name != "__call__" or call:
        data["model"]["call"] = method_name
    method = getattr(cls, method_name, None)
    if not callable(method):
        raise InterfaceError(f"{cls.__name__} has no method {method_name!r}")

    try:
        obj = cls(**_probe_kwargs(data, ("parameters",)))
    except Exception as e:
        comments[("outputs", None)] = f"probe construction failed ({e!r}); add the outputs by hand"
        return

    # Parameters kept as writable attributes *may* be tunable, but only if the step method
    # reads the attribute (not a value derived from it in __init__), so only suggest it.
    for name in data.get("parameters", {}):
        if _writable_attribute(obj, name) and _same(getattr(obj, name), data["parameters"][name].get("start")):
            comments.setdefault(("parameters", name), "kept as an attribute: add variability = \"tunable\" if the step reads it")

    _arguments(method, "inputs", data, comments, skip_self=True, constants_key="call_constants")
    before = _numeric_attributes(obj)
    kwargs = {**_probe_kwargs(data, ("inputs",)), **_time_kwargs(data.get("time", {}))}
    try:
        result = getattr(obj, method_name)(**kwargs)
    except Exception as e:
        comments[("outputs", None)] = f"probe call failed ({e!r}); add the outputs by hand"
        return
    after = _numeric_attributes(obj)

    if result is not None and result is not obj:
        _outputs_from_return(result, data, comments, default_name="y", is_class=True)
    taken = {*data.get("parameters", {}), *data.get("inputs", {}), *data.get("outputs", {})}
    for attr, value in after.items():
        if attr in taken:
            continue
        if attr not in before:
            data.setdefault("outputs", {})[attr] = _typed({}, value)
            comments[("outputs", attr)] = f"set by {method_name}()"
        elif not _same(before[attr], value):
            data.setdefault("locals", {})[attr] = _typed({}, value)
            comments[("locals", attr)] = f"changed by {method_name}()"
    _detect_states(data, comments, returned=result if isinstance(result, Mapping) else None, obj=obj)


def _pick_method(cls):
    for name in CALL_NAMES:
        if name == "__call__":
            if any("__call__" in vars(k) for k in cls.__mro__[:-1]):
                return name
        elif callable(getattr(cls, name, None)):
            return name
    public = [n for n, v in vars(cls).items() if not n.startswith("_") and inspect.isfunction(v)]
    if len(public) == 1:
        return public[0]
    raise InterfaceError(
        f"cannot tell which method of {cls.__name__} runs a step (public methods: {', '.join(public) or 'none'}); "
        "pass --call METHOD"
    )


# ---------------- shared ----------------

def _arguments(fn, section, data, comments, skip_self=False, allow_time=True, constants_key="constants"):
    """Sort the arguments of fn into variables of `section` and time arguments.

    Arguments whose default is not an FMI value (None, tuples, objects) keep their code
    default; they are listed as commented-out constants so the user can override them.
    """
    variables = data.setdefault(section, {})
    time_args = data.get("time", {})
    params = list(inspect.signature(fn).parameters.values())
    if skip_self and params:
        params = params[1:]
    for p in params:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD, p.POSITIONAL_ONLY):
            continue
        if allow_time and p.name in TIME_NAMES:
            time_args[p.name] = TIME_NAMES[p.name]
            continue
        default = None if p.default is p.empty else p.default
        if p.default is p.empty or isinstance(default, SCALARS):
            info = _type_info(default, p.annotation)
            if p.default is p.empty:
                comments[(section, p.name)] = "no default in the code: check the start value"
            elif type(default) is int and p.annotation is not int:
                comments[(section, p.name)] = "Integer because the default is an int; write a float start for Real"
            variables[p.name] = info
        elif isinstance(default, enum.Enum):
            variables[p.name] = {
                "enum": f"{type(default).__module__}:{type(default).__qualname__}",
                "start": default.name,
            }
        else:
            comments[("model", f"{constants_key}.{p.name}")] = _constant(default)
    if time_args and allow_time:
        data["time"] = time_args
    if not variables:
        data.pop(section)


def _type_info(value, annotation=inspect.Parameter.empty):
    if value is None:
        hint = {float: 0.0, int: 0, bool: False, str: ""}.get(annotation, 0.0)
        return {"start": hint}
    if isinstance(value, int) and not isinstance(value, bool) and annotation is float:
        return {"start": float(value)}
    if isinstance(value, SCALARS):
        return {"start": value}
    return {"start": float(value)}


def _constant(value):
    """How a non-FMI default would be written as a constant (for a commented-out example)."""
    text = repr(value)
    try:
        if ast.literal_eval(text) == value:
            return {"python": text}
    except (ValueError, SyntaxError):
        pass
    module, qualname = getattr(value, "__module__", None), getattr(value, "__qualname__", None)
    if module and qualname and "<" not in qualname:
        return {"ref": f"{module}:{qualname}"}
    return None


def _probe_kwargs(data, sections):
    kwargs = {}
    for section in sections:
        for name, info in data.get(section, {}).items():
            if "enum" in info:
                from fmugen.templates.model import resolve_reference
                kwargs[name] = getattr(resolve_reference(info["enum"]), info["start"])
            else:
                kwargs[name] = info.get("start", 0.0)
    return kwargs


def _time_kwargs(time_args):
    return {arg: (PROBE_STEP_SIZE if source == "step_size" else 0.0) for arg, source in time_args.items()}


def _typed(info, value):
    """Type of an output seen in the probe; ints become Real (a probe often just returns 0)."""
    if isinstance(value, enum.Enum):
        info["enum"] = f"{type(value).__module__}:{type(value).__qualname__}"
    elif isinstance(value, (bool, str)):
        info["type"] = _type_name(value)
    return info


def _outputs_from_return(result, data, comments, default_name, is_class):
    outputs = data.setdefault("outputs", {})
    if isinstance(result, Mapping):
        items = [(str(k), v, f"return:{k}") for k, v in result.items()]
    elif isinstance(result, (tuple, list)):
        items = [(f"{default_name}{i}", v, f"return:{i}") for i, v in enumerate(result)]
    elif _fmi_value(result):
        items = [(default_name, result, "return")]
    elif result is not None and hasattr(result, "__dict__"):
        items = [(k, v, f"return:{k}") for k, v in vars(result).items() if not k.startswith("_")]
    else:
        items = []
    for name, value, source in items:
        if not name.isidentifier() or not _fmi_value(value):
            comments[("outputs", None)] = f"skipped {name!r}: not an FMI value or not a valid name"
            continue
        # from = "return:<name>" is the default for functions
        outputs[name] = _typed({} if source == f"return:{name}" and not is_class else {"from": source}, value)
    if not outputs:
        data.pop("outputs")


def _detect_states(data, comments, returned, obj):
    """An input named x_prev whose next value is returned or stored as x_next / x is a state."""
    inputs = data.get("inputs", {})
    for name in list(inputs):
        if not name.endswith("_prev"):
            continue
        base = name[: -len("_prev")]
        for candidate in (f"{base}_next", base):
            if returned is not None and candidate in returned:
                source = f"return:{candidate}"
            elif obj is not None and hasattr(obj, candidate):
                source = f"attr:{candidate}"
            else:
                continue
            info = inputs.pop(name)
            data.setdefault("states", {})[name] = {**info, "next": source}
            comments[("states", name)] = f"fed back from {source} after each step"
            break
    if not inputs:
        data.pop("inputs", None)


def _numeric_attributes(obj):
    try:
        attrs = vars(obj)
    except TypeError:
        return {}
    return {k: v for k, v in attrs.items() if not k.startswith("_") and _fmi_value(v)}


def _writable_attribute(obj, name):
    if name not in getattr(obj, "__dict__", {}):
        prop = inspect.getattr_static(type(obj), name, None)
        return isinstance(prop, property) and prop.fset is not None
    return True


def _fmi_value(value):
    return isinstance(value, (*SCALARS, enum.Enum)) or type(value).__name__ in ("float64", "float32", "int64", "int32", "bool_")


def _same(a, b):
    try:
        return a == b or (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b))
    except Exception:
        return False


def _type_name(value):
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, int):
        return "Integer"
    if isinstance(value, str):
        return "String"
    return "Real"


# ---------------- TOML output ----------------

SECTION_ORDER = ("experiment", "time", "parameters", "calculated_parameters", "inputs", "states", "outputs", "locals")
HEADER = """\
# fmugen.toml: how this Python model becomes an FMU. Reference: docs/config.md
# Generated by `fmugen init`; check the start values, add units, and remove what you don't need.
"""


def render_toml(data, comments=None):
    comments = comments or {}
    lines = [HEADER]
    lines.append("[model]")
    for key, value in data["model"].items():
        lines.append(f"{_key(key)} = {_value(value)}")
    for table in ("constants", "call_constants"):
        examples = [
            (key.split(".", 1)[1], example) for (section, key), example in comments.items()
            if section == "model" and key.startswith(table + ".")
        ]
        if examples:
            lines.append("")
            lines.append("# Arguments whose code default is not an FMI value; the default is used.")
            lines.append("# To override one, uncomment the table header and the line.")
            lines.append(f"# [model.{table}]")
            for name, example in examples:
                lines.append(f"# {_key(name)} = {_value(example)}" if example else f"# {_key(name)} = ...")

    for section in SECTION_ORDER:
        table = data.get(section)
        note = comments.get((section, None))
        if not table and not note:
            continue
        lines.append("")
        lines.append(f"[{section}]")
        if note:
            lines.append(f"# {note}")
        for name, value in (table or {}).items():
            lines.append(_with_comment(f"{_key(name)} = {_value(value)}", comments.get((section, name))))
    return "\n".join(lines) + "\n"


def _with_comment(line, comment):
    return f"{line}  # {comment}" if comment else line


def _key(key):
    return key if key.replace("_", "").replace("-", "").isalnum() and key.isascii() else json.dumps(key)


def _value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }" if value else "{}"
    raise TypeError(f"cannot write {value!r} to TOML")
