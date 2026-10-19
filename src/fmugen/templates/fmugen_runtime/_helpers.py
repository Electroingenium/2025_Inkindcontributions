"""Standalone utility functions used by Engine, CompositeEngine and the build-time tools."""
from fmugen.templates.fmugen_runtime._constants import (
    FLOAT_TYPES, INT_RANGES, TRUE_STRINGS, FALSE_STRINGS, SPEC_VERSION, DEFAULT_VALUES, Status,
)
import ast
import builtins
import contextlib
import copy
import dataclasses
import datetime
import importlib
import inspect
import json
import logging
import math
import os
import pickle
import random
import sys
import tempfile
import traceback
import types
import typing
import warnings
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path


# ================= helpers =================


def _clock_of(var):
    clocks = var.get("clocks")
    return clocks[0] if clocks else None


def setup_sys_path(interface, resources_dir):
    for path in reversed(interface.get("sys_path", [])):
        path = str((Path(resources_dir) / path).resolve())
        if path not in sys.path:
            sys.path.insert(0, path)


def load_entry(interface, resources_dir):
    """Return (module, entry object)."""
    setup_sys_path(interface, resources_dir)
    entry = interface["entry"]
    module = importlib.import_module(entry["module"])
    return module, getattr(module, entry["name"])


def rng_states():
    """States of the global random number generators the model may draw from (random, numpy,
    torch), so a rolled-back step draws the same numbers again."""
    states = {"random": random.getstate()}
    numpy = sys.modules.get("numpy")
    if numpy is not None:
        states["numpy"] = numpy.random.get_state()
    torch = sys.modules.get("torch")
    if torch is not None and hasattr(torch, "get_rng_state"):
        states["torch"] = torch.get_rng_state()
        if torch.cuda.is_available() and torch.cuda.is_initialized():
            states["torch.cuda"] = torch.cuda.get_rng_state_all()
    return states


def set_rng_states(states):
    if "random" in states:
        random.setstate(states["random"])
    if "numpy" in states and "numpy" in sys.modules:
        sys.modules["numpy"].random.set_state(states["numpy"])
    torch = sys.modules.get("torch")
    if torch is not None:
        if "torch" in states:
            torch.set_rng_state(states["torch"])
        if "torch.cuda" in states:
            torch.cuda.set_rng_state_all(states["torch.cuda"])


def split_global(ref):
    """'package.module:NAME' -> (module, 'NAME') for [model] globals."""
    module_name, _, name = ref.partition(":")
    module = importlib.import_module(module_name)
    if not hasattr(module, name):
        raise AttributeError(f"module {module_name} has no global {name!r}")
    return module, name


def resolve_reference(ref):
    """'package.module:attr.path' (or dotted 'package.module.attr') -> the object."""
    if ":" in ref:
        module_name, _, attr = ref.partition(":")
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as e:
            # 'pybamm.lithium_ion:SPM': lithium_ion is an attribute of pybamm (set lazily), not a submodule
            if e.name is None or not (module_name + ".").startswith(e.name + ".") or "." not in module_name:
                raise
            try:
                return resolve_reference(f"{module_name}.{attr}")
            except (ImportError, AttributeError):
                raise e from None
        return get_path(module, attr)
    parts = ref.split(".")
    for i in range(len(parts), 0, -1):  # longest importable module prefix
        try:
            module = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        return get_path(module, ".".join(parts[i:])) if i < len(parts) else module
    raise ImportError(f"cannot import {ref!r}")


def dump_state(state):
    """pickle, else cloudpickle (lambdas, local functions), else dill (when installed); the first
    byte says which."""
    try:
        return b"P" + pickle.dumps(state)
    except Exception as e:
        error = e
    for prefix, name in ((b"C", "cloudpickle"), (b"D", "dill")):
        try:
            return prefix + importlib.import_module(name).dumps(state)
        except ImportError:
            continue
        except Exception as e:
            error = e
    raise error


def load_state(data):
    kind, payload = data[:1], data[1:]
    if kind == b"C":
        import cloudpickle  # noqa: F401  (its pickles load with pickle once it is importable)
    elif kind == b"D":
        import dill
        return dill.loads(payload)
    elif kind != b"P":
        raise ValueError("not an FMU state saved by this FMU")
    return pickle.loads(payload)


def split_item(name):
    """'pair[0]' -> ('pair', 0); 'params[key]' -> ('params', 'key'); 'u.temp' -> ('u', Field('temp'));
    'x' -> ('x', None)."""
    if "." in name and "[" not in name:
        base, _, field = name.partition(".")
        return base, Field(field)
    if not name.endswith("]") or "[" not in name:
        return name, None
    base, _, key = name[:-1].partition("[")
    key = key.strip().strip("'\"")
    return base, int(key) if key.isdigit() else key


class Field(str):
    """The field name in to = "arg:u.temp": u is an object (dataclass, pydantic, attrs) built from its fields."""


def assemble_items(bound, fn=None):
    """Combine {"pair[0]": a, "pair[1]": b, "u.T": c, "x": d} into {"pair": (a, b), "u": U(T=c), "x": d}.
    Objects are built from fn's signature: its default for that argument with the fields replaced,
    else the class in its annotation called with the fields."""
    result, items = {}, {}
    for name, value in bound.items():
        base, key = split_item(name)
        if key is None:
            result[name] = value
        else:
            items.setdefault(base, {})[key] = value
    for base, parts in items.items():
        if all(isinstance(k, Field) for k in parts):
            result[base] = build_object(fn, base, {str(k): v for k, v in parts.items()})
        elif any(isinstance(k, Field) for k in parts):
            raise ValueError(f"{base}: use either fields (arg:{base}.name) or items (arg:{base}[key]), not both")
        elif all(isinstance(k, int) for k in parts):
            if sorted(parts) != list(range(len(parts))):
                raise ValueError(f"{base}: tuple items must be numbered 0, 1, 2, ... without gaps")
            result[base] = tuple(parts[i] for i in range(len(parts)))
        else:
            result[base] = parts
    return result


_OBJECT_ARGS = {}


def object_argument(fn, name):
    """(default instance or None, class or None) of fn's argument `name`, from its signature."""
    key = (getattr(fn, "__func__", fn), name)
    if key not in _OBJECT_ARGS:
        target = fn.__init__ if isinstance(fn, type) else fn
        param = inspect.signature(fn).parameters.get(name)
        default = None if param is None or param.default is inspect.Parameter.empty else param.default
        try:
            cls = typing.get_type_hints(target).get(name)
        except Exception:
            cls = None
        if typing.get_origin(cls) in (typing.Union, types.UnionType):   # Optional[Inputs]
            rest = [a for a in typing.get_args(cls) if a is not type(None)]
            cls = rest[0] if len(rest) == 1 else None
        _OBJECT_ARGS[key] = default, cls if isinstance(cls, type) else None
    return _OBJECT_ARGS[key]


def build_object(fn, name, fields):
    if fn is None:
        raise ValueError(f"{name}: cannot tell which object to build from {sorted(fields)}")
    default, cls = object_argument(fn, name)
    if default is not None:
        if dataclasses.is_dataclass(default):
            return dataclasses.replace(default, **fields)
        if hasattr(default, "model_copy"):          # pydantic 2
            return default.model_copy(update=fields)
        if hasattr(type(default), "__attrs_attrs__"):
            import attrs
            return attrs.evolve(default, **fields)
        if isinstance(default, tuple) and hasattr(default, "_replace"):   # a namedtuple
            return default._replace(**fields)
        obj = copy.copy(default)
        for field, value in fields.items():
            setattr(obj, field, value)
        return obj
    if cls is None:
        raise ValueError(f"{name}: no default and no class annotation to build it from {sorted(fields)}")
    return cls(**fields)


def keyword_constants(constants):
    """The constants passed by keyword: all but those named "0", "1", ... (positions of *args)."""
    return {k: v for k, v in constants.items() if not k.isdigit()}


def is_literal_constant(value):
    """Whether a constant is a value (resolved again on reset), not a { call = ... } or a reference."""
    return not (isinstance(value, dict) and len(value) == 1 and ("call" in value or "ref" in value))


def resolve_constant(value):
    if isinstance(value, dict) and len(value) == 1:
        if "python" in value:
            return ast.literal_eval(value["python"])
        if "ref" in value:
            return resolve_reference(value["ref"])
        if "call" in value:
            return call_reference(value["call"])
    return value


def parse_call_text(text):
    """'module:function(arg, key=arg, ...)' -> (target, [arg nodes], {key: arg node}); no call is made."""
    target, paren, rest = text.partition("(")
    if not paren:
        return target.strip(), [], {}
    if not rest.rstrip().endswith(")"):
        raise ValueError(f"{text!r}: missing ')'")
    node = ast.parse(f"_({rest}", mode="eval").body
    if any(k.arg is None for k in node.keywords) or any(isinstance(a, ast.Starred) for a in node.args):
        raise ValueError(f"{text!r}: * and ** arguments are not supported")
    return target.strip(), list(node.args), {k.arg: k.value for k in node.keywords}


def call_reference(text):
    """Call 'module:function(args)' and return the result, e.g. load_from_hub(repo_id="sb3/x",
    filename="m.zip"). Without parentheses, 'module:attr.path' is the object itself, not called
    (a function to pass, an enum member). Arguments: see call_argument."""
    target, paren, _ = text.partition("(")
    if not paren:
        return resolve_reference(target.strip())
    target, args, kwargs = parse_call_text(text)
    return resolve_reference(target)(*[call_argument(a) for a in args],
                                     **{k: call_argument(v) for k, v in kwargs.items()})


def call_argument(node):
    """The value of an argument in a call constant: a Python literal; a dotted name of an importable
    object or a builtin (numpy.sin, float); a call of one (numpy.linspace(0, 1, 5), float("inf")); or
    a list, tuple, set or dict of these."""
    with contextlib.suppress(ValueError, SyntaxError, TypeError):
        return ast.literal_eval(node)
    if isinstance(node, ast.Name) and hasattr(builtins, node.id):
        return getattr(builtins, node.id)
    if isinstance(node, (ast.Name, ast.Attribute)):
        return resolve_reference(ast.unparse(node))
    if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
        if any(k.arg is None for k in node.keywords) or any(isinstance(a, ast.Starred) for a in node.args):
            raise ValueError(f"{ast.unparse(node)!r}: * and ** arguments are not supported")
        return call_argument(node.func)(*[call_argument(a) for a in node.args],
                                        **{k.arg: call_argument(k.value) for k in node.keywords})
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        items = [call_argument(e) for e in node.elts]
        return {ast.List: list, ast.Tuple: tuple, ast.Set: set}[type(node)](items)
    if isinstance(node, ast.Dict) and None not in node.keys:
        return {call_argument(k): call_argument(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = call_argument(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    raise ValueError(f"{ast.unparse(node)!r}: arguments must be literals, names of importable objects, "
                     "calls of those, or lists/tuples/dicts of these")


def converter(var):
    """The function applied to a value before the model gets it (`convert`)."""
    if var["convert"] == "pint":   # a quantity in the variable's unit, from pint's application registry
        import pint
        registry, unit = pint.get_application_registry(), var.get("unit", "")
        return lambda value: registry.Quantity(value, unit)
    return resolve_reference(var["convert"])


def _labelled(obj):
    return type(obj).__module__.split(".")[0] in ("pandas", "xarray") and hasattr(obj, "keys")


def plain_number(value, unit=None):
    """A pint quantity (anything with .magnitude and .units) or an astropy one as a number, in `unit`
    when given;
    a one-value pandas/xarray column as its value."""
    if type(value).__module__.split(".")[0] in ("pandas", "xarray") and getattr(value, "size", None) == 1:
        value = value.item()
    if hasattr(value, "magnitude") and hasattr(value, "units"):
        return value.m_as(unit) if unit and hasattr(value, "m_as") else value.magnitude
    if hasattr(value, "unit") and hasattr(value, "to_value"):   # an astropy Quantity
        try:
            return value.to_value(unit) if unit else value.value
        except Exception:   # a unit astropy doesn't know: the value in its own unit
            return value.value
    return value


def get_path(obj, path):
    """Follow a dotted path through attributes, mapping keys and sequence indexes: "state.T", "rewards.speed", "4.x",
    "X.value.-1" (the last element)."""
    for part in path.split("."):
        if isinstance(obj, Mapping) and (part in obj or not hasattr(obj, part)) or _labelled(obj) and part in obj:   # "options.update": the method
            obj = obj[part]
        elif part.lstrip("-").isdigit() and part.count("-") <= 1 and isinstance(obj, (tuple, list)):
            try:
                obj = obj[int(part)]
            except TypeError as e:   # a list-like wrapping a single value (a GEKKO variable before its first solve)
                raise IndexError(f"{part}: {e}") from e
        else:
            obj = getattr(obj, part)
    return obj


def set_path(obj, path, value):
    *parents, last = path.split(".")
    for part in parents:
        obj = getattr(obj, part)
    setattr(obj, last, value)


def pick(result, key):
    if key is None:
        return result
    if isinstance(result, Mapping) and key in result:   # a key that itself contains dots
        return result[key]
    return get_path(result, key)


def describe(source):
    if source["kind"] == "return":
        return "the return value" + (f" [{source['name']!r}]" if source.get("name") else "")
    return f"attribute {source['name']!r}"


def flatten(value):
    if isinstance(value, (list, tuple)):
        return [x for item in value for x in flatten(item)]
    return [value]


def reshape(flat, dims):
    if len(dims) <= 1:
        return list(flat)
    step = len(flat) // dims[0]
    return [reshape(flat[i * step:(i + 1) * step], dims[1:]) for i in range(dims[0])]


def _is_number(text):
    try:
        float(text)
    except ValueError:
        return False
    return True


def coerce(fmi_type, value):
    if fmi_type in FLOAT_TYPES:
        return float(value)
    if fmi_type in INT_RANGES or fmi_type == "Enumeration":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"{value!r} is not an integer")
        value = int(value)
        low, high = INT_RANGES.get(fmi_type, (-2**63, 2**63 - 1))
        if not low <= value <= high:
            raise ValueError(f"{value} is out of range for {fmi_type}")
        return value
    if fmi_type == "Boolean":
        if isinstance(value, str):
            text = value.strip().lower()
            if text in TRUE_STRINGS:
                return True
            if text in FALSE_STRINGS:
                return False
            raise ValueError(f"{value!r} is not a Boolean")
        return bool(value)
    if fmi_type == "Binary":
        if isinstance(value, str):
            return bytes.fromhex(value)
        return bytes(value)
    return str(value)


def _quiet_debug_logging():
    """Inside UniFMU's backend, raise the root logger from DEBUG to INFO.

    The backend's main.py calls logging.basicConfig(level=logging.DEBUG), so every library logs
    its debug records to the console: numba writes about 3 MB while compiling antropy's functions.
    UniFMU 0.14 crashes (its dispatcher panics) when the backend writes that much, and the importer
    then waits forever. INFO and above still reach the console and the importer's log.
    """
    root = logging.getLogger()
    if "UNIFMU_DISPATCHER_ENDPOINT" in os.environ and root.level < logging.INFO:
        root.setLevel(logging.INFO)


def _capture_output(enabled):
    """With `fmugen build --capture-output`, inside UniFMU's backend process, send stdout and
    stderr (file descriptors 1 and 2) to a file.

    UniFMU 0.14 crashes when its backend writes more than about 4 KB to the console, which
    models that print warnings or progress bars do. The output then goes to the importer's
    log instead (Engine._forward_output). Outside UniFMU (build probe, tests), nothing is
    redirected.
    """
    if not enabled or "UNIFMU_DISPATCHER_ENDPOINT" not in os.environ:
        return None
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    sink = tempfile.TemporaryFile()
    for fd in (1, 2):
        with contextlib.suppress(OSError):
            os.dup2(sink.fileno(), fd)
    return sink


UINT64_MAX = 2**64 - 1


def fraction(value):
    """float -> (counter, resolution) for FMI 3 *Fraction functions; both are uint64, so a value
    that needs a larger resolution (1e-20) is rounded to the nearest fraction that fits."""
    f = Fraction(str(value))
    if f.denominator > UINT64_MAX:
        f = f.limit_denominator(UINT64_MAX)
    return f.numerator, f.denominator
