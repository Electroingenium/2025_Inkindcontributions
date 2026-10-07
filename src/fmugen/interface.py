"""Infer a fmugen.toml from an ordinary Python model.

`infer_config()` imports the model and inspects the entry function or class: its
signatures give the parameters and inputs, and its source code (static.py) what it
returns and which attributes it sets. The model is not called. With probe=True
(`fmugen init --probe`) it is also called once with the start values, which finds
what reading the code can't: array sizes, exact types, results built at runtime, and
whether the object can be pickled. The result is a config dict (the same shape as
fmugen.toml) plus comments explaining each guess; `render_toml()` writes it out for the
user to review. `fmugen build model.py` runs the same inference in memory.
"""
import ast
import contextlib
import dataclasses
import enum
import importlib
import importlib.util
import inspect
import json
import math
import sys
import types
import typing
from collections.abc import Mapping
from pathlib import Path

from fmugen import static
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


def infer_config(target, call=None, config_dir=None, fmi_version=None, starts=None, setup=None, kind=None,
                 create=None, probe=False, converts=None):
    """Return (config dict, {(section, name): comment}) for a model target.

    With fmi_version=3, list/tuple/numpy values become array variables and bytes become Binary.
    `starts` ({argument: value}) gives probe/start values for arguments, e.g. ones without a
    default; `setup` (list of "module:function(args)" / "method") is run before the probe.
    `create` names a classmethod that builds the object (e.g. "from_pretrained").
    `probe`: also call the model once (setup, construction, one step); otherwise it is never called.
    `converts` ({argument: "module:function" or "numpy"}) sets how arguments are passed in.

    The model is imported (and probed) in config_dir, as it will run inside the FMU with
    [model] cwd, so files it opens by a relative path are found.
    """
    path, _module_name, name = parse_target(target)
    config_dir = Path(config_dir or (path.parent if path else ".")).resolve()
    if path:
        target = f"{path.resolve()}" + (f":{name}" if name else "")
    with contextlib.chdir(config_dir):
        return _infer_config(target, call, config_dir, fmi_version, starts, setup, kind, create, probe, converts)


def _infer_config(target, call, config_dir, fmi_version, starts, setup, kind, create, probe, converts):
    arrays = True   # FMI 2 writes arrays as one scalar per element; see _fmi2_types
    starts = dict(starts or {})
    if fmi_version != 3:
        for name, value in starts.items():
            if isinstance(value, bytes):
                raise InterfaceError(f"--start {name}: bytes need --fmi 3 (FMI 2 has no Binary variables)")
    path, module_name, name = parse_target(target)
    try:
        module = load_module(path) if path else importlib.import_module(module_name)
    except ImportError as e:
        raise InterfaceError(f"cannot import {target}: {e} (is it installed in this environment?)") from e
    entry = _pick_entry(module, name)

    if path:
        rel = Path(path).resolve().relative_to(config_dir).as_posix()
        entry_ref = f"{rel}:{entry.__name__}"
    else:
        entry_ref = f"{module_name}:{entry.__name__}"

    data = {"model": {"entry": entry_ref}}
    if fmi_version:
        data["model"]["fmi_version"] = fmi_version
    if path:
        sources = _local_sources(Path(path).resolve(), config_dir)
        if sources:
            data["model"]["sources"] = sources
    if setup:
        data["model"]["setup"] = list(setup)
    if kind == "function":
        data["model"]["kind"] = "function"
    comments = {}
    options = {"arrays": arrays, "starts": starts, "probe": probe, "converts": dict(converts or {})}
    if inspect.isclass(entry) and kind != "function":
        _infer_class(entry, call, data, comments, create=create, **options)
    elif call and kind != "function":
        # a function with --call is a factory: called once, --call runs on what it returns
        if create:
            raise InterfaceError("--create only applies to classes; a function with --call is already a factory")
        _infer_class(None, call, data, comments, factory=entry, **options)
    else:
        if call or create:
            raise InterfaceError("--call and --create only apply to classes")
        _infer_function(entry, data, comments, **options)
    _add_data_files(data, comments, config_dir, Path(path).resolve() if path else None)
    _add_globals(data, comments, module, config_dir if path else None)
    if fmi_version == 3:
        _rename_reserved(data, comments, is_class="call" in data["model"] or inspect.isclass(entry))
    else:
        _fmi2_types(data, comments)
    variables = {n for sec in ("parameters", "inputs", "states") for n in data.get(sec, {})}
    unknown = set(converts or {}) - variables
    if unknown:
        raise InterfaceError(f"--convert names that are not arguments of the model: {sorted(unknown)}")
    unused = set(starts) - variables \
        - {n for table in ("constants", "call_constants") for n in data["model"].get(table, {})} \
        - {str(info.get("to", "")).partition(":")[2].partition("[")[0]
           for sec in ("parameters", "inputs", "states") for info in data.get(sec, {}).values()}         - {str(info["to"]).partition(":")[2] for sec in ("parameters", "inputs", "states")
           for info in data.get(sec, {}).values() if "." in str(info.get("to", ""))}
    if unused:
        raise InterfaceError(f"--start names that are not arguments of the model: {sorted(unused)}")
    return data, comments


FMI2_TYPES = {"Float32": None, "Float64": None, **{t: "Integer" for t in (
    "Int8", "UInt8", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64")}}


def _fmi2_types(data, comments):
    """FMI 2 has only Real, Integer, Boolean and String: map the FMI 3 types found, and leave out
    what FMI 2 can't hold (bytes, arrays sized by structural parameters)."""
    for section in ("parameters", "inputs", "states", "outputs", "locals"):
        variables = data.get(section, {})
        for name, info in list(variables.items()):
            dims = info.get("dimensions", [])
            if info.get("type") == "Binary" or any(isinstance(d, str) for d in dims):
                del variables[name]
                comments[(section, f"#{name}")] = f"{name}: bytes and resizable arrays need --fmi 3"
            elif info.get("type") in FMI2_TYPES:
                if FMI2_TYPES[info["type"]] is None:
                    del info["type"]
                else:
                    info["type"] = FMI2_TYPES[info["type"]]
        if section in data and not variables:
            del data[section]
    data.pop("structural_parameters", None)


def _rename_reserved(data, comments, is_class):
    """FMI 3 reserves `time`: an output or local read from the model's own `time` becomes `model_time`."""
    for section in ("outputs", "locals"):
        variables = data.get(section, {})
        if "time" in variables and "model_time" not in variables:
            info = variables.pop("time")
            info.setdefault("from", "attr:time" if is_class else "return:time")
            variables["model_time"] = info
            comments.pop((section, "time"), None)
            comments[(section, "model_time")] = "the model's `time` (FMI 3 reserves that name)"


def _run_setup(data, obj=None):
    """Run [model] setup steps for the probe: functions before construction, methods after."""
    from fmugen.config import _setup
    from fmugen.templates.fmugen_runtime import (
        get_path,
        resolve_constant,
        resolve_reference,
    )
    for step in _setup(data["model"].get("setup", []), is_class=True):
        is_method = ":" not in step["call"]
        if is_method != (obj is not None):
            continue
        target = get_path(obj, step["call"]) if is_method else resolve_reference(step["call"])
        target(*[resolve_constant(a) for a in step["args"]],
               **{k: resolve_constant(v) for k, v in step["kwargs"].items()})


def _local_sources(entry_file, config_dir):
    """Files and directories under config_dir that the model imported (besides the entry file).

    A module inside a subdirectory contributes the whole top-level directory, so packages
    and flat sibling imports are copied together.
    """
    sources = set()
    for module in list(sys.modules.values()):
        file = getattr(module, "__dict__", {}).get("__file__")  # no getattr: lazy modules import on access
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


def _add_data_files(data, comments, config_dir, entry_file):
    """Files next to the config that the model opens by a relative path, found as string start
    values (a file name argument) or string literals in the entry file: copied with `sources`, and
    `cwd = "."` so the model finds them inside the FMU."""
    texts = [info["start"] for section in ("parameters", "inputs") for info in data.get(section, {}).values()
             if isinstance(info.get("start"), str)]
    texts += [c["python"] for table in ("constants", "call_constants")
              for c in data["model"].get(table, {}).values() if isinstance(c, dict) and "python" in c]
    if entry_file is not None:
        try:
            tree = ast.parse(entry_file.read_text(encoding="utf-8"))
            texts += [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        except (OSError, SyntaxError, UnicodeDecodeError):
            pass
    sources = data["model"].get("sources", [])
    found = []
    for text in dict.fromkeys(t.strip("'\"") for t in texts):
        if not text or len(text) > 255 or "\n" in text or Path(text).is_absolute():
            continue
        try:
            file = (config_dir / text).resolve()
            is_file = file.is_file()
        except (OSError, ValueError):
            continue
        if not is_file or not file.is_relative_to(config_dir) or file.suffix == ".py" or file == entry_file:
            continue
        rel = file.relative_to(config_dir).as_posix()
        if not any(rel == s or rel.startswith(f"{s}/") for s in sources + found):
            found.append(rel)
    if found:
        data["model"]["sources"] = sources + found
        data["model"]["cwd"] = "."
        comments[("model", "cwd")] = (f"the model opens {', '.join(found)} by a relative path: "
                                      "they are copied into the FMU and the model runs in that folder")


def _add_globals(data, comments, entry_module, local_dir=None):
    """[model] globals: module-level variables holding numbers or arrays that the model's own
    package rebinds while it runs. They are put back on reset and saved with the FMU state."""
    top = entry_module.__name__.split(".")[0]
    def local(m):   # a module of the user's project (next to the config), not an installed one
        file = getattr(m, "__dict__", {}).get("__file__")
        return local_dir is not None and file and Path(file).resolve().is_relative_to(local_dir)             and "site-packages" not in Path(file).parts

    def ours(m):
        return m.__name__ == top or m.__name__.startswith(top + ".") or local(m)

    # the entry module, and the package's modules it uses (as modules, or by their functions and classes)
    reached, todo = {entry_module.__name__: entry_module}, [entry_module]
    while todo:
        for value in list(vars(todo.pop()).values()):
            used = value if isinstance(value, types.ModuleType) else sys.modules.get(getattr(value, "__module__", None) or "")
            if isinstance(used, types.ModuleType) and used.__name__ not in reached and ours(used):
                reached[used.__name__] = used
                todo.append(used)
    found = []
    for module in reached.values():
        for name in static.written_globals(module):
            value = module.__dict__.get(name)
            if isinstance(value, (bool, int, float, str)) or _number_like(value) or _array_info(value) is not None:
                found.append(f"{module.__name__}:{name}")
    if found:
        data["model"]["globals"] = sorted(set(found))
        comments[("model", "globals")] = ("module-level state the model changes while it runs: "
                                          "put back on reset and saved with the FMU state")


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

def _infer_function(fn, data, comments, arrays=False, starts=None, probe=False, converts=None):
    _arguments(fn, "inputs", data, comments, arrays=arrays, starts=starts)
    _apply_converts(data, converts)
    returned_names, seen = set(), set()
    if probe:
        try:
            _run_setup(data)
            result = _probe_call(fn, data, comments)
        except Exception as e:
            comments[("outputs", None)] = f"probe call failed ({e!r}); outputs below are read from the code"
        else:
            seen = _outputs_from_return(result, data, comments, default_name="y", is_class=False, arrays=arrays)
            returned_names |= seen
    if inspect.isclass(fn):   # kind = "function": the new object is the result; its constructor sets the outputs
        kinds = static.class_attributes(fn, "__init__")[0]
        public = [a for a, k in kinds.items() if not a.startswith("_") and k not in ("other", "none")
                  and (k != "array" or arrays)]
        read = static.Returned(public, {a: f"return:{a}" for a in public}, {a: kinds[a] for a in public})
        if not public and static.function_node(fn.__init__) is None:
            read = static.Returned(unknown="no Python source to read")
    else:
        read = static.returned(fn)
    _add_returned(read, data, comments, is_class=False, arrays=arrays, probe=probe, seen=seen)
    _detect_states(data, comments, returned=returned_names | set(read.names), attrs=set())


# ---------------- classes ----------------

def _infer_class(cls, call, data, comments, arrays=False, starts=None, create=None, factory=None, probe=False,
                 converts=None):
    """Infer a class model; with `factory` (a function), the object comes from calling it instead."""
    if factory and cls is None:
        cls = static.factory_class(factory)   # from its return annotation; else known only by calling it
    method_name = call or _pick_method(cls)
    if create:
        if not callable(getattr(cls, create, None)):
            raise InterfaceError(f"{cls.__name__} has no classmethod {create!r}")
        data["model"]["create"] = create
    if factory:
        constructor = factory
        # The step method's arguments may be known only once the object exists: names the factory
        # declares go to it, everything else to the step method (even if the factory takes **kwargs).
        declared = inspect.signature(factory).parameters
        init_starts = {k: v for k, v in (starts or {}).items() if k in declared}
        call_starts = {k: v for k, v in (starts or {}).items() if k not in declared}
    else:
        constructor = getattr(cls, create) if create else cls.__init__   # a bound classmethod has no cls argument
        init_starts, call_starts = _assign_starts(constructor, getattr(cls, method_name, None), starts or {})
    _arguments(constructor, "parameters", data, comments, skip_self=not (create or factory), allow_time=False,
               arrays=arrays, starts=init_starts, positional=False)
    _apply_converts(data, converts)

    if method_name != "__call__" or call:
        data["model"]["call"] = method_name
    if not factory and not callable(getattr(cls, method_name, None)):
        raise InterfaceError(f"{cls.__name__} has no method {method_name!r}")

    seen_returns, seen_attrs, obj = set(), set(), None
    if probe:
        obj, seen_returns, seen_attrs = _probe_class(cls, method_name, data, comments, arrays, call_starts,
                                                     create, factory, converts)
    elif cls is None:
        comments[("inputs", None)] = (f"the object {factory.__name__}() returns is known only by running it: add the "
                                      f"inputs and outputs of {method_name}() by hand, or run init --probe")
    else:
        method = inspect.getattr_static(cls, method_name)
        _arguments(getattr(cls, method_name), "inputs", data, comments,
                   skip_self=not isinstance(method, (staticmethod, classmethod)), constants_key="call_constants",
                   arrays=arrays, starts=call_starts)
        _apply_converts(data, converts)
        copies = static.init_copies(cls) if not factory and not create else set()
        for name in data.get("parameters", {}):
            if name in copies:
                comments.setdefault(("parameters", name),
                                    "kept as an attribute: add variability = \"tunable\" if the step reads it")
        comments[("model", "#save_state")] = (
            "save_state = false  # not checked without --probe: set it if the model holds a device, file, "
            "socket or ONNX session")
    if obj is None and cls is None:
        return   # a factory whose object type isn't known without running it

    read = static.returned(getattr(cls, method_name)) if cls is not None else static.Returned()
    _add_returned(read, data, comments, is_class=True, arrays=arrays, probe=probe, seen=seen_returns)
    if cls is not None:
        _add_attributes(cls, method_name, data, comments, arrays, probe, seen_attrs)
    attrs = set(seen_attrs) | (set(dir(obj)) if obj is not None else set())
    if cls is not None:
        attrs |= set(static.assigned_attributes(cls, method_name)) | set(static.assigned_attributes(cls, "__init__"))
        attrs |= set(static.own_properties(cls))
    _detect_states(data, comments, returned=seen_returns | set(read.names), attrs=attrs)


def _probe_class(cls, method_name, data, comments, arrays, call_starts, create, factory, converts):
    """--probe: construct the object, call the step method once, and read what changed.

    Returns (object or None, returned keys, attribute names seen).
    """
    try:
        _run_setup(data)
        build = factory or (getattr(cls, create) if create else cls)
        obj = build(**_probe_constants(data, "constants"), **_probe_args(data, ("parameters",), build)[1])
        _run_setup(data, obj)
    except Exception as e:
        comments[("outputs", None)] = f"probe construction failed ({e!r}); outputs below are read from the code"
        if cls is not None:
            _arguments(getattr(cls, method_name), "inputs", data, comments, skip_self=True,
                       constants_key="call_constants", arrays=arrays, starts=call_starts)
            _apply_converts(data, converts)
        return None, set(), set()
    if factory:
        method = getattr(obj, method_name, None)   # bound: no self argument
        if not callable(method):
            raise InterfaceError(f"the object {factory.__name__}() returns has no method {method_name!r}")
    else:
        method = getattr(cls, method_name)

    # Parameters kept as writable attributes *may* be tunable, but only if the step method
    # reads the attribute (not a value derived from it in __init__), so only suggest it.
    for name in data.get("parameters", {}):
        if _writable_attribute(obj, name) and _same(getattr(obj, name), data["parameters"][name].get("start")):
            comments.setdefault(("parameters", name), "kept as an attribute: add variability = \"tunable\" if the step reads it")

    _arguments(method, "inputs", data, comments, skip_self=not factory, constants_key="call_constants",
               arrays=arrays, starts=call_starts)
    _apply_converts(data, converts)
    before = _numeric_attributes(obj, arrays)
    try:
        result = _probe_call(getattr(obj, method_name), data, comments, constants_key="call_constants")
    except Exception as e:
        comments[("outputs", None)] = f"probe call failed ({e!r}); outputs below are read from the code"
        return obj, set(), set(getattr(obj, "__dict__", {}))
    after = _numeric_attributes(obj, arrays)
    _check_picklable(obj, data, comments)

    returned = set()
    if result is not None and result is not obj:
        returned = _outputs_from_return(result, data, comments, default_name="y", is_class=True, arrays=arrays)
    taken = {*data.get("parameters", {}), *data.get("inputs", {}), *data.get("outputs", {})}
    for attr, value in _property_values(obj, arrays).items():   # read-only views such as T1 = sensor reading
        if attr not in taken:
            data.setdefault("outputs", {})[attr] = _typed({}, value, arrays)
            comments[("outputs", attr)] = "a property of the object"
    taken |= set(data.get("outputs", {}))
    for attr, value in after.items():
        if attr in taken:
            continue
        if attr not in before:
            data.setdefault("outputs", {})[attr] = _typed({}, value, arrays)
            comments[("outputs", attr)] = f"set by {method_name}()"
        elif not _same(before[attr], value):
            data.setdefault("locals", {})[attr] = _typed({}, value, arrays)
            comments[("locals", attr)] = f"changed by {method_name}()"
    return obj, returned, set(getattr(obj, "__dict__", {})) | set(_property_values(obj, arrays))


# ---------------- results read from the code ----------------

def _taken(data):
    return {n for section in ("parameters", "structural_parameters", "inputs", "states", "outputs", "locals")
            for n in data.get(section, {})}


def _add_returned(read, data, comments, is_class, arrays, probe, seen):
    """Outputs from what the code returns (static.returned). With --probe, only ones the probe didn't see."""
    if read.unknown:
        if not probe:
            comments[("outputs", None)] = (f"outputs could not be read from the code ({read.unknown}); "
                                           "add them by hand, or run init --probe")
        return
    if read.array:
        if arrays and not probe:   # the size can't be read from the code
            comments[("outputs", "#y")] = ('y = { from = "return", dimensions = [...] }  # an array: set its '
                                           'dimensions and uncomment, or run init --probe')
        return
    taken = _taken(data) | set(seen)
    # "y4" and "y4.rewards" when the probe found "y4.rewards.speed"
    parents = {".".join(n.split(".")[:i]) for n in taken for i in range(1, n.count(".") + 1)}
    for name in read.names:
        if name in taken or name in parents:
            continue
        if probe and read.sources[name] == "return" and data.get("outputs"):
            continue   # the probe already split the whole return value (a table, an object) into outputs
        kind = read.types.get(name)
        source = read.sources[name]
        copied = None
        if kind and kind.startswith("arg:"):   # an argument returned as it is: the same type as its variable
            arg = kind[len("arg:"):]
            copied = next((info for sec in ("parameters", "inputs", "states")
                           for n, info in data.get(sec, {}).items()
                           if n == arg or str(info.get("to", "")).endswith(f":{arg}")), None)
            kind = "array" if copied and "dimensions" in copied else None
        if kind == "array":
            if arrays and not probe:
                comments[("outputs", f"#{name}")] = (f'{name} = {{ from = "{source}", dimensions = [...] }}  '
                                                     "# an array: set its dimensions and uncomment, or run init --probe")
            continue
        if kind in ("other", "none"):
            continue
        info = {} if (source == f"return:{name}" and not is_class) else {"from": source}
        if copied:
            info.update({k: v for k, v in copied.items() if k in ("type", "enum", "items")})
        elif kind in ("Boolean", "String", "Integer"):
            info["type"] = kind
        data.setdefault("outputs", {})[name] = info
        if probe:
            comments[("outputs", name)] = "from the code; not seen in the probe"


def _add_attributes(cls, method_name, data, comments, arrays, probe, seen):
    """Outputs and locals from the attributes the step method assigns, and the object's own properties."""
    in_step, in_init = static.class_attributes(cls, method_name)
    taken = _taken(data) | set(seen)
    for attr, kind in in_step.items():
        if attr.startswith("_") or attr in taken:
            continue
        kind = static._merge([kind, in_init.get(attr)])
        section = "locals" if attr in in_init else "outputs"
        if kind == "array":
            if arrays and not probe:
                comments[(section, f"#{attr}")] = (f"{attr} = {{ dimensions = [...] }}  # an array set by "
                                                   f"{method_name}(): set its dimensions and uncomment, or run init --probe")
            continue
        if kind == "other":
            continue
        info = {"type": kind} if kind in ("Boolean", "String") else {}
        data.setdefault(section, {})[attr] = info
        comments[(section, attr)] = ("from the code; not seen in the probe" if probe else
                                     f"{'changed' if section == 'locals' else 'set'} by {method_name}()")
    for name, kind in static.own_properties(cls).items():
        if name in _taken(data) or name in seen:
            continue
        if kind:   # annotated as a number, bool or str
            data.setdefault("outputs", {})[name] = {"type": kind} if kind != "Real" else {}
            comments[("outputs", name)] = "from the code; not seen in the probe" if probe else "a property of the object"
        elif not probe:   # without an annotation its value could be anything: reading it would run code
            comments[("outputs", f"#{name}")] = (f"{name} = {{}}  # a property of the object (type unknown): "
                                                 "uncomment if it is a number, or run init --probe")


def _apply_converts(data, converts):
    """--convert NAME=module:function (or NAME=numpy): how an argument is passed to the model."""
    for name, converter in (converts or {}).items():
        for section in ("parameters", "inputs", "states"):
            info = data.get(section, {}).get(name)
            if info is None:
                continue
            info.pop("numpy", None), info.pop("convert", None)
            if converter == "numpy":
                info["numpy"] = True
            else:
                info["convert"] = converter


ARRAY_RETRIES = ("numpy", "torch:tensor")   # tried in order when a probe call fails with list inputs


def _probe_constants(data, table):
    """Constants set in the config (e.g. computed by a call), resolved as the FMU would."""
    from fmugen.templates.fmugen_runtime import resolve_constant
    return {k: resolve_constant(v) for k, v in data["model"].get(table, {}).items()}


def _probe_call(fn, data, comments, constants_key="constants"):
    """Call fn with the probe inputs. If it fails and array inputs are plain lists, retry with them
    as numpy arrays, then torch tensors (when installed), and keep the first that works."""
    def call():
        args, kwargs = _probe_args(data, ("inputs",), fn)
        kwargs.update(_time_kwargs(data.get("time", {})))
        kwargs.update(_probe_constants(data, constants_key))
        return fn(*args, **kwargs)

    try:
        return call()
    except Exception:
        plain = [info for info in data.get("inputs", {}).values()
                 if "dimensions" in info and not info.get("numpy") and not info.get("convert")]
        if not plain:
            raise
        for converter in ARRAY_RETRIES:
            module = "numpy" if converter == "numpy" else converter.partition(":")[0]
            if importlib.util.find_spec(module) is None:
                continue
            for info in plain:
                info.update({"numpy": True} if converter == "numpy" else {"convert": converter})
            try:
                result = call()
            except Exception:
                for info in plain:
                    info.pop("numpy", None), info.pop("convert", None)
                continue
            names = [n for n, info in data["inputs"].items() if any(info is p for p in plain)]
            shown = "numpy arrays" if converter == "numpy" else converter.replace(":", ".") + "(...)"
            for name in names:
                comments[("inputs", name)] = f"passed as {shown}: the probe failed with lists"
            return result
        raise


def _check_picklable(obj, data, comments):
    """Pick [model] save_state: FMU state save/restore pickles the model object (as the runtime does:
    pickle, else cloudpickle). If that fails, save only the attributes that can be pickled; if none
    can, declare save/restore unsupported."""
    from fmugen.templates.fmugen_runtime import dump_state
    try:
        dump_state(obj)
        return
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:120]
    try:
        attrs = vars(obj)
    except TypeError:
        attrs = {}
    saved, skipped = [], []
    for name, value in attrs.items():
        try:
            dump_state(value)
            saved.append(name)
        except Exception:
            skipped.append(name)
    if saved and skipped:
        data["model"]["save_state"] = saved
        comments[("model", "save_state")] = (
            f"the whole object can't be pickled ({error}); saved: these attributes only. Not saved, "
            f"kept as they are on restore: {', '.join(skipped)}. Check those don't change during a simulation, "
            "else set save_state = false")
    else:
        data["model"]["save_state"] = False
        comments[("model", "save_state")] = f"the model object can't be pickled ({error}): " \
                                            "the FMU can't save and restore its state"


def _assign_starts(init, method, starts):
    """Split --start values between constructor and step method arguments.

    A name goes to the argument that has no default (it needs a value); on a tie, to the
    step method. Names neither declares go to whichever accepts **kwargs (method first).
    """
    def params(fn):
        try:
            return inspect.signature(fn).parameters if fn is not None else {}
        except (TypeError, ValueError):
            return {}

    init_p, call_p = params(init), params(method)
    init_starts, call_starts = {}, {}
    for name, value in starts.items():
        in_init, in_call = init_p.get(name), call_p.get(name)
        if in_init and in_call:
            target = init_starts if (in_init.default is in_init.empty and in_call.default is not in_call.empty) \
                else call_starts
        elif in_init or in_call:
            target = init_starts if in_init else call_starts
        elif any(p.kind is p.VAR_KEYWORD for p in call_p.values()):
            target = call_starts
        elif any(p.kind is p.VAR_KEYWORD for p in init_p.values()):
            target = init_starts
        else:
            continue  # reported as unused
        target[name] = value
    return init_starts, call_starts


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

def _arguments(fn, section, data, comments, skip_self=False, allow_time=True, constants_key="constants",
               arrays=False, starts=None, positional=True):
    """Sort the arguments of fn into variables of `section` and time arguments.

    Arguments whose default is not an FMI value (None, tuples, objects) keep their code
    default; they are listed as commented-out constants so the user can override them.
    """
    variables = data.setdefault(section, {})
    time_args = data.get("time", {})
    starts = starts or {}
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):  # e.g. some C extensions
        comments[(section, None)] = f"cannot inspect the signature of {getattr(fn, '__qualname__', fn)}; " \
                                    "add the variables by hand (to = \"pos:N\" for positional arguments)"
        params = []
    if skip_self and params:
        params = params[1:]
    position = 0
    for p in params:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.kind is p.POSITIONAL_ONLY and not positional:
            continue
        if allow_time and p.name in TIME_NAMES and p.name not in starts:
            time_args[p.name] = TIME_NAMES[p.name]
            continue
        if isinstance(starts.get(p.name), dict) and "call" in starts[p.name]:
            data["model"].setdefault(constants_key, {})[p.name] = dict(starts[p.name])
            continue
        if p.name in starts and _split_items(p, starts[p.name], variables, section, comments, arrays):
            continue
        if p.name not in starts and _split_fields(fn, p, variables, section, comments, starts, arrays):
            continue
        if p.name in starts and not arrays and isinstance(starts[p.name], (list, tuple, bytes)):
            raise InterfaceError(f"--start {p.name}: arrays and bytes need --fmi 3 (FMI 2 has only scalar variables)")
        has_default = p.default is not p.empty or p.name in starts
        default = starts.get(p.name, None if p.default is p.empty else p.default)
        before = len(variables)
        if not has_default or isinstance(default, SCALARS):
            info = _type_info(default, p.annotation)
            if p.name in starts:
                comments[(section, p.name)] = "start from --start"
            elif not has_default:
                comments[(section, p.name)] = "no default in the code: check the start value"
            elif type(default) is int and static.unwrap_optional(p.annotation) is not int:
                comments[(section, p.name)] = "Integer because the default is an int; write a float start for Real"
            variables[p.name] = info
        elif isinstance(default, enum.Enum):
            variables[p.name] = {
                "enum": f"{type(default).__module__}:{type(default).__qualname__}",
                "start": default.name,
            }
        elif arrays and isinstance(default, bytes):
            variables[p.name] = {"type": "Binary", "start": default.hex()}
        elif arrays and _array_info(default):
            variables[p.name] = _array_info(default, with_start=True)
        else:
            comments[("model", f"{constants_key}.{p.name}")] = _constant(default)
        if len(variables) > before and "dimensions" in variables[p.name]:
            converter = _converter(p.annotation)
            if converter == "numpy":
                variables[p.name]["numpy"] = True
            elif converter:
                variables[p.name]["convert"] = converter
                comments.setdefault((section, p.name), f"passed as {converter.replace(':', '.')}(...)")
        if p.kind is p.POSITIONAL_ONLY and len(variables) > before:
            variables[p.name]["to"] = f"pos:{position}"
            position += 1
    if any(p.kind is p.VAR_KEYWORD for p in params):  # **kwargs: --start values become keyword arguments
        names = {p.name for p in params}
        for name, value in starts.items():
            if name in names:
                continue
            if isinstance(value, SCALARS):
                variables[name] = _type_info(value)
            elif arrays and _array_info(value):
                variables[name] = _array_info(value, with_start=True)
            else:
                raise InterfaceError(f"--start {name}: {value!r} is not an FMI value")
            comments[(section, name)] = "start from --start (passed through **kwargs)"
    if time_args and allow_time:
        data["time"] = time_args
    if not variables:
        data.pop(section)


ARRAY_CONVERTERS = {"torch.Tensor": "torch:tensor", "ndarray": "numpy", "jax.Array": "jax.numpy:asarray",
                    "tf.Tensor": "tensorflow:constant"}


def _converter(annotation):
    """How an array argument must be passed, from its annotation: "numpy", "module:function", or None."""
    if annotation is inspect.Parameter.empty:
        return None
    text = annotation if isinstance(annotation, str) else repr(annotation)
    return next((conv for name, conv in ARRAY_CONVERTERS.items() if name in text), None)


def _split_items(p, value, variables, section, comments, arrays):
    """A tuple of arrays (or a dict) passed as one argument becomes one variable per item,
    bound with to = "arg:NAME[i]" / "arg:NAME[key]". Returns whether it was split."""
    import typing
    if isinstance(value, tuple) and len(value) > 1 and not (arrays and _array_info(value)):
        keys = list(range(len(value)))
        names = [f"{p.name}_{i}" for i in keys]
        hints = typing.get_args(p.annotation) if p.annotation is not p.empty else ()
    elif isinstance(value, dict) and value and all(isinstance(k, str) and k.isidentifier() for k in value):
        keys = list(value)
        names = keys
        hints = ()
    else:
        return False
    items = [value[k] for k in keys]
    if not all(isinstance(item, SCALARS) or (arrays and _array_info(item)) for item in items):
        return False
    for i, (key, name, item) in enumerate(zip(keys, names, items)):
        info = _array_info(item, with_start=True) if (arrays and _array_info(item)) else _type_info(item)
        if "dimensions" in info:
            from fmugen.templates.fmugen_runtime import flatten
            flat = flatten(list(item))
            if all(isinstance(x, int) and not isinstance(x, bool) for x in flat):   # e.g. atomic numbers, indices
                info.update(type="Int32", start=flat)
        info["to"] = f"arg:{p.name}[{key}]"
        converter = _converter(hints[i]) if i < len(hints) else None
        if converter == "numpy":
            info["numpy"] = True
        elif converter and "dimensions" in info:
            info["convert"] = converter
        variables[name] = info
        comments[(section, name)] = f"item {key!r} of the argument {p.name}"
    return True


def _object_fields(cls):
    """[(field, type hint, default or empty)] of a dataclass, pydantic model or attrs class, else None."""
    if not isinstance(cls, type):
        return None
    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        hints = {}
    empty = inspect.Parameter.empty
    if dataclasses.is_dataclass(cls):
        missing = dataclasses.MISSING
        return [(f.name, hints.get(f.name), empty if f.default is missing and f.default_factory is missing
                 else (f.default if f.default is not missing else f.default_factory()))
                for f in dataclasses.fields(cls) if f.init]
    if hasattr(cls, "model_fields") and isinstance(cls.model_fields, dict):   # pydantic 2
        return [(name, f.annotation, empty if f.is_required() else f.get_default(call_default_factory=True))
                for name, f in cls.model_fields.items()]
    if hasattr(cls, "__attrs_attrs__"):
        import attrs
        return [(a.name, hints.get(a.name, a.type), empty if a.default is attrs.NOTHING
                 else (a.default.factory() if isinstance(a.default, attrs.Factory) else a.default))
                for a in cls.__attrs_attrs__ if a.init]
    return None


def _split_fields(fn, p, variables, section, comments, starts, arrays):
    """An argument that is a dataclass / pydantic / attrs object (by its default or its annotation)
    becomes one variable per field, NAME_FIELD, bound with to = "arg:NAME.FIELD". Fields that aren't
    FMI values keep the default's value; without a default, they must have their own default."""
    if p.default is None:
        return False   # None means "not given" to the model: it stays a constant, as for any argument
    default = None if p.default is p.empty else p.default
    try:
        cls = typing.get_type_hints(fn).get(p.name)
    except Exception:
        cls = p.annotation if isinstance(p.annotation, type) else None
    cls = type(default) if default is not None else static.unwrap_optional(cls)
    fields = _object_fields(cls)
    if not fields:
        return False
    found = {}
    for field, hint, field_default in fields:
        value = getattr(default, field) if default is not None else starts.get(f"{p.name}.{field}", field_default)
        if value is p.empty:   # a required field without a start: a variable if its annotation is a number
            if static.unwrap_optional(hint) not in (float, int, bool, str):
                return False   # can't be built from FMI values
            value = None
        elif not isinstance(value, SCALARS) and not (arrays and _array_info(value)):
            continue   # None or not an FMI value: the default's value (or the field's default) is kept
        info = _array_info(value, with_start=True) if value is not None and not isinstance(value, SCALARS)             else _type_info(value, static.unwrap_optional(hint))
        if isinstance(info.get("start"), int) and not isinstance(info["start"], bool)                 and static.unwrap_optional(hint) is float:
            info["start"] = float(info["start"])
        info["to"] = f"arg:{p.name}.{field}"
        found[f"{p.name}_{field}"] = info
        if value is None:
            comments[(section, f"{p.name}_{field}")] = f"field {field!r} of {p.name} ({cls.__name__}); no default: check the start value"
        else:
            comments[(section, f"{p.name}_{field}")] = f"field {field!r} of {p.name} ({cls.__name__})"
    if not found:
        return False
    variables.update(found)
    return True


def _type_info(value, annotation=inspect.Parameter.empty):
    annotation = static.unwrap_optional(annotation)
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


def _probe_args(data, sections, fn=None):
    """(positional args, keyword args) for a probe call from the inferred start values."""
    values = _probe_kwargs(data, sections)
    positional = sorted(
        (int(info["to"].split(":")[1]), name)
        for section in sections for name, info in data.get(section, {}).items()
        if str(info.get("to", "")).startswith("pos:")
    )
    args = [values.pop(name) for _, name in positional]
    from fmugen.templates.fmugen_runtime import assemble_items
    targets = {name: str(info["to"]).partition(":")[2] for section in sections
               for name, info in data.get(section, {}).items()
               if any(c in str(info.get("to", "")).partition(":")[2] for c in "[.")
               and str(info["to"]).startswith(("arg:", "init:"))}
    for name, target in targets.items():
        values[target] = values.pop(name)
    return args, assemble_items(values, fn)


def _probe_kwargs(data, sections):
    from fmugen.templates.fmugen_runtime import reshape, resolve_reference
    kwargs = {}
    for section in sections:
        for name, info in data.get(section, {}).items():
            if "enum" in info:
                kwargs[name] = getattr(resolve_reference(info["enum"]), info["start"])
            elif "dimensions" in info:
                value = reshape(info["start"], info["dimensions"])
                if info.get("numpy"):
                    import numpy
                    value = numpy.array(value)
                kwargs[name] = value
            elif info.get("type") == "Binary":
                kwargs[name] = bytes.fromhex(info["start"])
            else:
                kwargs[name] = info.get("start", 0.0)
            if info.get("convert"):
                kwargs[name] = resolve_reference(info["convert"])(kwargs[name])
    return kwargs


def _time_kwargs(time_args):
    return {arg: (PROBE_STEP_SIZE if source == "step_size" else 0.0) for arg, source in time_args.items()}


def _typed(info, value, arrays=False):
    """Type of an output seen in the probe; ints become Real (a probe often just returns 0)."""
    if _unit_of(value):
        info["unit"] = _unit_of(value)
    value = _scalar_of(value)
    if arrays and isinstance(value, bytes):
        info["type"] = "Binary"
    elif arrays and _array_info(value):
        # numpy = true only matters for values passed *into* the model
        info.update({k: v for k, v in _array_info(value).items() if k not in ("numpy", "convert")})
    elif type(value).__name__ == "float32":
        info["type"] = "Float32" if arrays else "Real"
    elif isinstance(value, enum.Enum):
        info["enum"] = f"{type(value).__module__}:{type(value).__qualname__}"
    elif isinstance(value, (bool, str)):
        info["type"] = _type_name(value)
    return info


def _outputs_from_return(result, data, comments, default_name, is_class, arrays=False):
    """Outputs from a probe result. Returns the names of the parts it looked at (dict keys,
    tuple positions y0, y1, ...), also those left out because they aren't FMI values."""
    outputs = data.setdefault("outputs", {})
    if isinstance(result, Mapping):
        items = [(str(k), v, f"return:{k}") for k, v in result.items()]
    elif _table_children(result) is not None:   # pandas Series / one-row DataFrame, xarray Dataset
        items = [(k, v, f"return:{k}") for k, v in _table_children(result)]
    elif arrays and _array_info(result):
        items = [(default_name, result, "return")]
    elif isinstance(result, tuple) and hasattr(result, "_fields"):   # NamedTuple: use the field names
        items = [(field, getattr(result, field), f"return:{field}") for field in result._fields]
    elif isinstance(result, (tuple, list)):
        items = [(f"{default_name}{i}", v, f"return:{i}") for i, v in enumerate(result)]
    elif _fmi_value(result):
        items = [(default_name, result, "return")]
    elif result is not None and hasattr(result, "__dict__"):
        items = [(k, v, f"return:{k}") for k, v in vars(result).items() if not k.startswith("_")]
    else:
        items = []
    looked_at = {name for name, _, _ in items}
    items = [leaf for name, value, source in items for leaf in _nested(name, value, source, arrays)]
    taken = {n for section in ("parameters", "inputs", "states") for n in data.get(section, {})}
    for name, value, source in items:
        if name in taken:  # e.g. an object that echoes its inputs as attributes
            continue
        if not _dotted_name(name) or not _fmi_value(value, arrays):
            comments[("outputs", None)] = f"skipped {name!r}: not an FMI value or not a valid name"
            continue
        # from = "return:<name>" is the default for functions
        info = {} if source == f"return:{name}" and not is_class else {"from": source}
        outputs[name] = _typed(info, value, arrays)
        scalar = _scalar_of(value)
        if isinstance(scalar, int) and not isinstance(scalar, bool) and "type" not in outputs[name]:
            comments[("outputs", name)] = 'an int in the probe; Real, since results often vary: type = "Integer" if it is a count'
    if not outputs:
        data.pop("outputs")
    return looked_at


MAX_NESTING = 4


def _nested(name, value, source, arrays, depth=0):
    """(name, value, source) for each value inside nested dicts, NamedTuples, dataclasses and
    namespaces, named with dots: {"zone": {"T": 21}} gives ("zone.T", 21, "return:zone.T")."""
    if depth < MAX_NESTING and not _fmi_value(value, arrays):
        children = _children(value)
        if children:
            sep = ":" if source == "return" else "."
            return [leaf for key, child in children
                    for leaf in _nested(f"{name}.{key}", child, f"{source}{sep}{key}", arrays, depth + 1)]
    return [(name, value, source)]


def _children(value):
    table = _table_children(value)
    if table is not None:
        return table
    if isinstance(value, Mapping):
        return [(k, v) for k, v in value.items() if isinstance(k, str)]
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        return [(f, getattr(value, f)) for f in value._fields]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return [(f.name, getattr(value, f.name)) for f in dataclasses.fields(value)]
    if isinstance(value, types.SimpleNamespace):
        return list(vars(value).items())
    return []


def _table_children(value):
    """[(label, scalar)] for a pandas Series, a one-row pandas DataFrame or an xarray Dataset of
    single values (labels that are strings); None for anything else."""
    kind = type(value).__name__
    library = type(value).__module__.split(".")[0]
    try:
        if library == "pandas" and kind == "Series":
            pairs = list(value.items())
        elif library == "pandas" and kind == "DataFrame" and len(value) == 1:
            pairs = [(c, value[c].iloc[0]) for c in value.columns]
        elif library == "xarray" and kind == "Dataset":
            pairs = [(k, v.item()) for k, v in value.data_vars.items() if v.size == 1]
        else:
            return None
    except Exception:
        return None
    return [(k, v) for k, v in pairs if isinstance(k, str)]


def _dotted_name(name):
    return all(part.isidentifier() for part in name.split("."))


def _detect_states(data, comments, returned, attrs):
    """An input named x_prev whose next value is returned (a key in `returned`) or stored as an
    attribute (a name in `attrs`) x_next / x is a state."""
    inputs = data.get("inputs", {})
    for name in list(inputs):
        if not name.endswith("_prev"):
            continue
        base = name[: -len("_prev")]
        for candidate in (f"{base}_next", base):
            if candidate in returned:
                source = f"return:{candidate}"
            elif candidate in attrs:
                source = f"attr:{candidate}"
            else:
                continue
            info = inputs.pop(name)
            data.setdefault("states", {})[name] = {**info, "next": source}
            comments[("states", name)] = f"fed back from {source} after each step"
            break
    if not inputs:
        data.pop("inputs", None)


def _numeric_attributes(obj, arrays=False):
    try:
        attrs = vars(obj)
    except TypeError:
        return {}
    return {k: _snapshot(v) for k, v in attrs.items() if not k.startswith("_") and _fmi_value(v, arrays)}


def _snapshot(value):
    """A copy that later in-place changes (e.g. numpy `+=`) don't affect."""
    return value.copy() if hasattr(value, "copy") and not isinstance(value, (str, bytes)) else value


def _property_values(obj, arrays=False):
    """Public properties of the object whose current value is an FMI value.

    Only properties defined in the model's own package count: base classes from frameworks
    (torch.nn.Module, transformers' PreTrainedModel, ...) add properties that aren't model results.
    """
    package = type(obj).__module__.split(".")[0]
    own = {name for klass in type(obj).__mro__ if klass.__module__.split(".")[0] == package
           for name, member in vars(klass).items() if isinstance(member, property)}
    values = {}
    for name, prop in inspect.getmembers(type(obj), lambda m: isinstance(m, property)):
        if name.startswith("_") or prop.fget is None or name not in own:
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if _fmi_value(value, arrays):
            values[name] = _snapshot(value)
    return values


def _writable_attribute(obj, name):
    if name not in getattr(obj, "__dict__", {}):
        prop = inspect.getattr_static(type(obj), name, None)
        return isinstance(prop, property) and prop.fset is not None
    return True


NUMPY_SCALARS = ("float64", "float32", "int64", "int32", "int16", "int8", "uint64", "uint32", "uint16",
                 "uint8", "bool_")
NUMPY_TYPES = {"float32": "Float32", "float64": "Real", "int8": "Int8", "uint8": "UInt8", "int16": "Int16",
               "uint16": "UInt16", "int32": "Int32", "uint32": "UInt32", "int64": "Int64", "uint64": "UInt64",
               "bool": "Boolean"}


def _scalar_of(value):
    """The scalar inside a 0-dimensional array or tensor (numpy, torch, ...) or a pint quantity,
    else the value itself."""
    if hasattr(value, "magnitude") and hasattr(value, "units"):
        value = value.magnitude
    # numpy scalars (np.float32, ...) also have ndim 0, but are handled as they are, keeping their type
    if getattr(value, "ndim", None) == 0 and hasattr(value, "item") and type(value).__name__ not in NUMPY_SCALARS:
        try:
            return value.item()
        except Exception:
            return value
    return value


def _fmi_value(value, arrays=False):
    value = _scalar_of(value)
    if isinstance(value, (*SCALARS, enum.Enum)) or type(value).__name__ in NUMPY_SCALARS or _number_like(value):
        return True
    return arrays and (isinstance(value, bytes) or _array_info(value) is not None)


def _number_like(value):
    """Decimal, Fraction, numpy.float16, ... : anything that converts to a float or an int and isn't an array."""
    if getattr(value, "ndim", 0) or isinstance(value, (str, bytes, complex)):
        return False
    return hasattr(type(value), "__float__") or hasattr(type(value), "__index__")


def _unit_of(value):
    """The unit of a pint quantity, written compactly ("m/s"); None for anything else or dimensionless."""
    units = getattr(value, "units", None)
    if units is None or not hasattr(value, "magnitude"):
        return None
    try:
        return f"{units:~C}" or None
    except Exception:
        return str(units) or None


def _array_info(value, with_start=False):
    """{dimensions, type?, numpy?, start?} for a rectangular list/tuple/numpy array of numbers, else None."""
    if hasattr(value, "shape") and hasattr(value, "tolist") and getattr(value, "ndim", 0) > 0:
        from fmugen.templates.fmugen_runtime import flatten
        shape, flat = [int(n) for n in value.shape], flatten(value.tolist())
        fmi_type = NUMPY_TYPES.get(str(value.dtype).rpartition(".")[2])   # "float32", "torch.float32", ...
        if fmi_type is None:
            return None
        info = {"dimensions": shape}
        library = type(value).__module__.split(".")[0]
        if library == "numpy":
            info["numpy"] = True
        elif library == "torch":
            info["convert"] = "torch:tensor"
    elif isinstance(value, (list, tuple)) and value:
        shape = _shape(value)
        if shape is None:
            return None
        from fmugen.templates.fmugen_runtime import flatten
        flat = flatten(value)
        if all(isinstance(x, bool) for x in flat):
            fmi_type = "Boolean"
        elif all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in flat):
            fmi_type = "Real"
        else:
            return None
        info = {"dimensions": shape}
    else:
        return None
    if 0 in shape:
        return None
    if fmi_type != "Real":
        info["type"] = fmi_type
    if with_start:
        info["start"] = [float(x) for x in flat] if fmi_type in ("Real", "Float32") else flat
    return info


def _shape(value):
    if not isinstance(value, (list, tuple)):
        return []
    shapes = [_shape(item) for item in value]
    if not shapes or any(s is None or s != shapes[0] for s in shapes):
        return None
    return [len(value), *shapes[0]]


def _same(a, b):
    if hasattr(a, "tolist"):
        a = a.tolist()
    if hasattr(b, "tolist"):
        b = b.tolist()
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

SECTION_ORDER = ("experiment", "time", "structural_parameters", "parameters", "calculated_parameters",
                 "inputs", "states", "outputs", "locals")
CLOCKS_EXAMPLE = """
# FMI 3 clocks run model code on events; they can't be inferred. Example (docs/models.md#clocks):
# [clocks.sample]
# interval = 0.1            # a periodic input clock, ticked by the importer
# call = "sample"           # method (or function) run when it ticks
# [inputs]
# measurement = { start = 0.0, clocks = ["sample"] }   # passed to sample()
"""
HEADER = """\
# fmugen.toml: how this Python model becomes an FMU. Reference: docs/config.md
# Generated by `fmugen init`; check the start values, add units, and remove what you don't need.
"""


def render_toml(data, comments=None):
    comments = comments or {}
    lines = [HEADER]
    lines.append("[model]")
    for key, value in data["model"].items():
        if key not in ("constants", "call_constants"):
            lines.append(_with_comment(f"{_key(key)} = {_value(value)}", comments.get(("model", key))))
    if "save_state" not in data["model"] and ("model", "#save_state") in comments:
        lines.append(f"# {comments[('model', '#save_state')]}")
    for table in ("constants", "call_constants"):
        real = data["model"].get(table, {})
        examples = [
            (key.split(".", 1)[1], example) for (section, key), example in comments.items()
            if section == "model" and key.startswith(table + ".") and key.split(".", 1)[1] not in real
        ]
        if real or examples:
            lines.append("")
        if examples:
            lines.append("# Arguments whose code default is not an FMI value; the default is used.")
            lines.append("# To override one, uncomment the line" + ("." if real else " and the table header."))
        if real or examples:
            lines.append(f"[model.{table}]" if real else f"# [model.{table}]")
        for name, value in real.items():
            lines.append(_with_comment(f"{_key(name)} = {_value(value)}", "computed when the FMU initializes"
                                       if isinstance(value, dict) and "call" in value else None))
        for name, example in examples:
            lines.append(f"# {_key(name)} = {_value(example)}" if example else f"# {_key(name)} = ...")

    for section in SECTION_ORDER:
        table = data.get(section)
        note = comments.get((section, None))
        hints = [text for (sec, key), text in comments.items() if sec == section and str(key).startswith("#")]
        if not table and not note and not hints:
            continue
        lines.append("")
        lines.append(f"[{section}]")
        if note:
            lines.append(f"# {note}")
        for name, value in (table or {}).items():
            lines.append(_with_comment(f"{_key(name)} = {_value(value)}", comments.get((section, name))))
        lines.extend(f"# {text}" for text in hints)   # commented-out lines to complete by hand
    if data["model"].get("fmi_version") == 3:
        lines.append(CLOCKS_EXAMPLE.rstrip("\n"))
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
