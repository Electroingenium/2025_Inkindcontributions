"""Probing, output detection and state detection for interface inference."""
import dataclasses
import datetime
import enum
import importlib
import inspect
import math
import pickle
import sys
import types
import typing
from collections.abc import Mapping

from fmugen import static
from fmugen.config import InterfaceError
from fmugen.toml_output import _key, _value
from fmugen.arguments import (
    SCALARS, PROBED, DATETIME_BY_NAME, NO_SIGNATURE,
    _fmi_value, _array_info, _scalar_of, _number_like, _typed, _type_name, _same,
    _valid_name, _dotted_name, _misfit, _unfit_value, _unfit, _guessed,
    _apply_converts, _arguments, _only_varargs,
    _start_error, _state_base,
)

PROBE_STEP_SIZE = 1.0

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

def _probe_class(cls, method_name, data, comments, arrays, call_starts, create, factory, converts):
    """--probe: construct the object, call the step method once, and read what changed.

    Returns (object or None, returned keys, attribute names seen).
    """
    try:
        _run_setup(data)
        build = factory or (getattr(cls, create) if create else cls)
        args, kwargs = _probe_args(data, ("parameters",), build, "constants")
        obj = build(*args, **_probe_constants(data, "constants"), **kwargs)
        _run_setup(data, obj)
    except ConstantError:
        raise
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
    before, state_before = _numeric_attributes(obj, arrays), _state_bytes(obj)
    try:
        result = _probe_call(getattr(obj, method_name), data, comments, constants_key="call_constants")
    except ConstantError:
        raise
    except Exception as e:
        comments[("outputs", None)] = f"probe call failed ({e!r}); outputs below are read from the code"
        return obj, set(), set(getattr(obj, "__dict__", {}))
    comments[PROBED] = True
    after = _numeric_attributes(obj, arrays)
    state_after = _state_bytes(obj)
    if result is not None and _same(before, after) and (state_before is None or state_before == state_after):
        # the step changed nothing: running it at initialization too gives the outputs at the start time
        data["model"]["init_call"] = True
        comments[("model", "init_call")] = (f"{method_name}() changed nothing in the probe, so it also runs at "
                                            "initialization: outputs have values at the start time")
    _check_picklable(obj, data, comments)

    returned = set()
    if result is not None and result is not obj:
        returned = _outputs_from_return(result, data, comments, default_name="y", is_class=True, arrays=arrays)
    taken = {*data.get("parameters", {}), *data.get("inputs", {}), *data.get("outputs", {})}
    for attr, value in _property_values(obj, arrays).items():   # read-only views such as T1 = sensor reading
        if attr not in taken:
            data.setdefault("outputs", {})[attr] = _typed({}, value, arrays)
            comments[("outputs", attr)] = "a property of the object"
    unfit = _unfit_properties(obj, data, comments, arrays, taken)
    taken |= set(data.get("outputs", {})) | unfit
    taken |= _gekko_outputs(obj, data, comments, taken)
    taken |= static.foreign_attributes(type(obj))   # a library base's own state (GEKKO's csv_status)
    for attr, value in getattr(obj, "__dict__", {}).items():   # complex attributes (None ones are too common)
        if not attr.startswith("_") and attr not in taken and value is not None and _misfit(value):
            _unfit_value(comments, "outputs", attr, value, f"attr:{attr}", arrays)
            unfit.add(attr)
    for attr, value in after.items():
        if attr in taken:
            continue
        if attr not in before:
            data.setdefault("outputs", {})[attr] = _typed({}, value, arrays)
            comments[("outputs", attr)] = f"set by {method_name}()"
        elif not _same(before[attr], value):
            data.setdefault("locals", {})[attr] = _typed({}, value, arrays)
            comments[("locals", attr)] = f"changed by {method_name}()"
    _check_sizes(obj, method_name, data, comments)
    return obj, returned, set(getattr(obj, "__dict__", {})) | set(_property_values(obj, arrays)) | unfit


GEKKO_RESULTS = ("GKVariable", "GK_Intermediate", "GK_FV")   # Var/SV/CV, Intermediate, FV/MV (not Param, Const)


def _gekko_result(value):
    """The value of a solved GEKKO variable, intermediate, FV or MV at the end of its time horizon
    (m.time), or None: GEKKO keeps results in these objects, as `x.value` after `m.solve()`."""
    if not type(value).__module__.startswith("gekko.") \
            or not any(k.__name__ in GEKKO_RESULTS for k in type(value).__mro__):
        return None
    try:
        last = value.value[-1]
    except Exception:   # not solved yet: a single value
        return None
    return last if _fmi_value(last) else None


def _gekko_outputs(obj, data, comments, taken):
    """Outputs for the object's attributes that hold GEKKO results (`self.X = m.Var(...)`), and for
    dicts of them (`self.W = {"HOU1": m.Var(...)}`), read as their last value. Returns their names."""
    found = {}
    for attr, value in getattr(obj, "__dict__", {}).items():
        if attr.startswith("_"):
            continue
        if _gekko_result(value) is not None:
            found[attr] = (f"{attr}.value.-1", value)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(key, str) and "." not in key and key and _gekko_result(item) is not None:
                    found[_valid_name(f"{attr}.{key}")] = (f"{attr}.{key}.value.-1", item)
    names = set()
    for name, (path, value) in found.items():
        if name in taken:
            continue
        data.setdefault("outputs", {})[name] = _typed({"from": f"attr:{path}"}, _gekko_result(value))
        comments[("outputs", name)] = (f"a GEKKO {type(value).__name__}: its value at the end of the time "
                                       f"horizon (m.time); the whole trajectory is {path[:-3]}")
        names.add(name)
    return names

def _unfit_properties(obj, data, comments, arrays, taken):
    """Properties annotated as a number, bool or str (so the code alone would make them outputs) whose
    probe value isn't one, e.g. None, or that raised: commented out. Returns their names."""
    annotated = {name for name, kind in static.own_properties(type(obj)).items() if kind}
    unfit = set()
    for attr, value in _property_values(obj, arrays, everything=True).items():
        if attr in taken or attr not in annotated or (not isinstance(value, Exception) and _fmi_value(value, arrays)):
            continue
        if not _unfit_value(comments, "outputs", attr, value, f"attr:{attr}", arrays):
            why = (f"reading it raised {value!r} in the probe" if isinstance(value, Exception)
                   else f"a {type(value).__name__} in the probe, not an FMI value")
            _unfit(comments, "outputs", attr, why, [f'{_key(attr)} = {{ from = "attr:{attr}" }}'])
        unfit.add(attr)
    return unfit


def _check_sizes(obj, method_name, data, comments):
    """Call the step method a second time: an array whose size changes (a history that grows each
    call) can't be an FMI array, which has a fixed size."""
    sized = [(section, name, info) for section in ("outputs", "locals")
             for name, info in data.get(section, {}).items() if "dimensions" in info]
    if not sized:
        return
    from fmugen.templates.fmugen_runtime import get_path, pick
    try:
        result = _call_with_probe_inputs(getattr(obj, method_name), data, "call_constants")
    except Exception:
        return
    for section, name, info in sized:
        source = info.get("from", f"attr:{name}")
        kind, _, path = source.partition(":")
        try:
            value = pick(result, path or None) if kind == "return" else get_path(obj, path)
        except Exception as e:
            size = f"unreadable ({e!r})"
        else:
            new = _array_info(_scalar_of(value))
            size = new["dimensions"] if new else "not an array"
        if size == info["dimensions"]:
            continue
        del data[section][name]
        comments.pop((section, name), None)
        _unfit(comments, section, name, f"its size changed from {info['dimensions']} to {size} on a second probe "
               "call, and an FMI array has a fixed size", [f'{_key(name)} = {{ ' + (f'from = "{source}", ' if section == "outputs"
                                                                       else "") + "dimensions = [...] }"])
        if not data[section]:
            del data[section]

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
        if comments.get(PROBED):   # the probe's call worked, and didn't return it
            _unfit(comments, "outputs", name, "not in what the probe's call returned; reading it fails the step "
                   "whenever the model doesn't return it", [f'{_key(name)} = {{ from = "{source}" }}'])
            continue
        info = {} if (source == f"return:{name}" and not is_class) else {"from": source}
        if copied:
            info.update({k: v for k, v in copied.items() if k in ("type", "enum", "items")})
        elif kind in ("Boolean", "String", "Integer"):
            info["type"] = kind
        elif kind is None:
            _guessed(comments, name)
        if name in read.nullable and not probe:   # e.g. a database column: None fails the step
            comments[("outputs", f"#{name}")] = f"{_key(name)} = {_value(info)}"
            comments.setdefault(("outputs", None), "results that can be None (nullable database columns) are "
                                                   "commented out: uncomment the ones this model always has, "
                                                   "or run init --probe")
            continue
        data.setdefault("outputs", {})[name] = info
        if probe:
            comments[("outputs", name)] = "from the code; not seen in the probe"
        elif read.may_be_none and source == "return":
            comments[("outputs", name)] = "the code can also return None, which fails the step: check it, or run init --probe"


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
        if comments.get(PROBED) and section == "outputs":   # the probe's step worked, and didn't set it
            _unfit(comments, "outputs", attr, f"not set by {method_name}() in the probe; reading it fails the step "
                   "whenever the model hasn't set it", [f'{_key(attr)} = ' + (f'{{ type = "{kind}" }}' if kind in
                                                        ("Boolean", "String") else "{}")])
            continue
        info = {"type": kind} if kind in ("Boolean", "String") else {}
        if kind is None and section == "outputs":
            _guessed(comments, attr)
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

ARRAY_RETRIES = ("numpy", "torch:tensor")   # tried in order when a probe call fails with list inputs


def _probe_constants(data, table, positional=False):
    """Constants set in the config (e.g. computed by a call), resolved as the FMU would: the keyword
    ones, or with positional=True {position: value} of those named "0", "1", ... (passed to *args)."""
    from fmugen.templates.fmugen_runtime import resolve_constant
    values = {}
    for k, v in data["model"].get(table, {}).items():
        if k.isdigit() != positional:
            continue
        try:
            values[int(k) if positional else k] = resolve_constant(v)
        except Exception as e:
            what = f"call:{v['call']}" if isinstance(v, dict) and "call" in v else _value(v)
            raise ConstantError(f"[model] {table}.{k} = {what} fails: {type(e).__name__}: {e}") from e
    return values


class ConstantError(InterfaceError):
    """A constant (e.g. --start NAME=call:...) that can't be computed: the FMU would fail the same way."""


def _probe_call(fn, data, comments, constants_key="constants"):
    """Call fn with the probe inputs (see _probe_once). Arguments taken as date-times only by their
    name are checked: the call is also made with the number 0.0 there. Works only as a date-time:
    confirmed; only as a number: an ordinary input instead; both or neither: left as a guess."""
    guessed = [arg for arg in comments.get(DATETIME_BY_NAME, []) if isinstance(data.get("time", {}).get(arg), dict)]
    if not guessed:
        return _probe_once(fn, data, comments, constants_key)
    try:
        result, error = _probe_once(fn, data, comments, constants_key), None
    except Exception as e:
        result, error = None, e
    for arg in guessed:
        source = data["time"].pop(arg)
        data.setdefault("inputs", {})[arg] = {"start": 0.0}
        try:
            number_result = _probe_once(fn, data, comments, constants_key)
            number_ok = True
        except Exception:
            number_ok = False
        if error is not None and number_ok:   # not a date-time: keep it an input
            comments.pop(("time", arg), None)
            comments[("inputs", arg)] = (f"its name {arg!r} suggests a date-time, but the probe failed with one "
                                         "and worked with a number")
            result, error = number_result, None
            continue
        del data["inputs"][arg]
        if not data["inputs"]:
            del data["inputs"]
        data["time"][arg] = source
        if error is None and not number_ok:
            comments[("time", arg)] = comments[("time", arg)].replace(
                f"taken as a date-time from its name {arg!r} (not annotated): check it, or replace this with an "
                "input; ", "a date-time argument (the probe worked with one, not with a number): ")
    if not data.get("time"):
        data.pop("time", None)
    if error is not None:
        raise error
    return result


def _call_with_probe_inputs(fn, data, constants_key):
    args, kwargs = _probe_args(data, ("inputs",), fn, constants_key)
    kwargs.update(_time_kwargs(data.get("time", {})))
    kwargs.update(_probe_constants(data, constants_key))
    return fn(*args, **kwargs)


def _probe_once(fn, data, comments, constants_key="constants"):
    """Call fn with the probe inputs. If it fails and array inputs are plain lists, retry with them
    as numpy arrays, then torch tensors (when installed), and keep the first that works."""
    def call():
        return _call_with_probe_inputs(fn, data, constants_key)

    try:
        return call()
    except Exception:
        # A date-time epoch is naive (some models refuse time zones); others need one: retry in UTC
        naive = [source for source in data.get("time", {}).values()
                 if isinstance(source, dict) and datetime.datetime.fromisoformat(source["epoch"]).tzinfo is None]
        if naive:
            for source in naive:
                source["epoch"] += "+00:00"
            try:
                result = call()
            except Exception:
                for source in naive:
                    source["epoch"] = source["epoch"].removesuffix("+00:00")
            else:
                for arg, source in data["time"].items():
                    if any(source is s for s in naive):
                        comments[("time", arg)] += "; epoch in UTC: the probe failed without a time zone"
                return result
        plain = [info for info in data.get("inputs", {}).values()
                 if "dimensions" in info and not info.get("numpy") and not info.get("convert")]
        if not plain:
            result = _retry_as_arrays(call, data, comments)
            if result is _FAILED:
                raise
            return result
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


_FAILED = object()


def _retry_as_arrays(call, data, comments):
    """When a call fails with numbers as inputs, call it again with each number as a one-element numpy
    array (convert = "numpy:atleast_1d"): some libraries take only arrays (thermofeel's
    calculate_heat_index_simplified calls numpy.nonzero on its inputs). Returns the result, or _FAILED."""
    numbers = {name: info for name, info in data.get("inputs", {}).items()
               if isinstance(info.get("start"), (int, float)) and not isinstance(info.get("start"), bool)
               and "dimensions" not in info and not info.get("convert") and not info.get("numpy")}
    if not numbers or importlib.util.find_spec("numpy") is None:
        return _FAILED
    for info in numbers.values():
        info["convert"] = "numpy:atleast_1d"
    try:
        result = call()
    except Exception:
        for info in numbers.values():
            del info["convert"]
        return _FAILED
    for name in numbers:
        comments[("inputs", name)] = "passed as numpy.atleast_1d(...): the probe failed with plain numbers"
    return result

def _state_bytes(obj):
    """The object's attributes pickled, to tell whether a call changed them; None if they can't be."""
    try:
        return pickle.dumps(vars(obj))
    except Exception:
        return None


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

def _split_varargs(cls, create, method_name, init_starts, call_starts, data, comments, probe):
    """When the constructor and the step method both take only *args (SWIG classes such as
    openturns.Normal(mu, sigma).computePDF(x)), the signatures can't tell which --start values go
    where: _assign_starts gives them all to the constructor. With --probe, the first values (in
    --start order) go to the constructor, the rest to the method, trying the constructor with as
    many as possible first, and the first split where both calls work is kept."""
    method = getattr(cls, method_name, None)
    if create or method is None or not _only_varargs(cls.__init__) or not _only_varargs(method) \
            or len(init_starts) < 1:
        return init_starts, call_starts
    names = list(init_starts)
    if not probe:
        comments[("inputs", None)] = (f"{cls.__name__}() and {method_name}() both take *args: every --start value "
                                      f"was given to the constructor; run init --probe to split them")
        return init_starts, call_starts
    from fmugen.templates.fmugen_runtime import resolve_constant
    try:
        _run_setup(data)
        values = [resolve_constant(init_starts[n]) for n in names]
    except Exception:
        return init_starts, call_starts
    for k in range(len(names), -1, -1):
        try:
            getattr(cls(*values[:k]), method_name)(*values[k:], **{n: resolve_constant(v) for n, v in call_starts.items()})
        except Exception:
            continue
        if k < len(names):
            comments[("inputs", None)] = (f"{cls.__name__}() and {method_name}() both take *args: the probe worked "
                                          f"with {', '.join(names[:k]) or 'nothing'} for the constructor and "
                                          f"{', '.join(names[k:])} for {method_name}()")
        return ({n: init_starts[n] for n in names[:k]},
                {**{n: init_starts[n] for n in names[k:]}, **call_starts})
    return init_starts, call_starts

def _probe_args(data, sections, fn=None, constants_key=None):
    """(positional args, keyword args) for a probe call from the inferred start values (and the
    positional constants of `constants_key`)."""
    values = _probe_kwargs(data, sections)
    positional = [
        (int(info["to"].split(":")[1]), name)
        for section in sections for name, info in data.get(section, {}).items()
        if str(info.get("to", "")).startswith("pos:")
    ]
    by_position = {i: values.pop(name) for i, name in positional}
    if constants_key:
        by_position.update(_probe_constants(data, constants_key, positional=True))
    args = [by_position[i] for i in sorted(by_position)]
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
    kwargs = {}
    for arg, source in time_args.items():
        if isinstance(source, dict):   # { source = ..., epoch = ... }: a date-time
            kwargs[arg] = datetime.datetime.fromisoformat(source["epoch"])
        else:
            kwargs[arg] = {"step_size": PROBE_STEP_SIZE, "end_time": PROBE_STEP_SIZE}.get(source, 0.0)
    return kwargs

def _outputs_from_return(result, data, comments, default_name, is_class, arrays=False):
    """Outputs from a probe result. Returns the names of the parts it looked at (dict keys,
    tuple positions y0, y1, ...), also those left out because they aren't FMI values."""
    outputs = data.setdefault("outputs", {})
    wrapped = any(info.get("convert") == "numpy:atleast_1d" for info in data.get("inputs", {}).values())
    if wrapped and getattr(result, "size", None) == 1 and hasattr(result, "reshape"):
        result = result.reshape(())[()]   # numbers passed as one-element arrays: a number comes back as one
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
    elif _fmi_value(result) or (result is not None and _misfit(result)):
        items = [(default_name, result, "return")]
    elif result is not None and (hasattr(result, "__dict__") or _public_properties(result)):
        # an object: its public attributes and properties, e.g. uncertainties' nominal_value, std_dev
        public = {k: v for k, v in getattr(result, "__dict__", {}).items() if not k.startswith("_")}
        public.update({k: v for k, v in _public_properties(result).items() if k not in public})
        items = [(k, v, f"return:{k}") for k, v in public.items()]
    else:
        items = []
    looked_at = {name for name, _, _ in items}
    items = [leaf for name, value, source in items for leaf in _nested(name, value, source, arrays)]
    # keys that aren't names (radioactivedecay's "N-14"): a valid name, the real key kept in `from`
    items = [(_valid_name(name), value, source) for name, value, source in items]
    taken = {n for section in ("parameters", "inputs", "states") for n in data.get(section, {})}
    for name, value, source in items:
        if name in taken:  # e.g. an object that echoes its inputs as attributes
            continue
        if _dotted_name(name) and _unfit_value(comments, "outputs", name, value, source, arrays):
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


def _public_properties(obj):
    """{name: value} of the public properties of obj's class whose value is an FMI value; of
    properties that are the same object under several names (uncertainties' n and nominal_value),
    only the longest name."""
    by_property = {}
    for name in dir(type(obj)):
        # static lookup: getattr on the class runs descriptors, which can fail (SQLAlchemy hybrid properties)
        prop = inspect.getattr_static(type(obj), name, None)
        if isinstance(prop, property) and not name.startswith("_") \
                and len(name) > len(by_property.get(id(prop), "")):
            by_property[id(prop)] = name
    values = {}
    for name in sorted(by_property.values()):
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if _fmi_value(value):
            values[name] = value
    return values

def _detect_states(data, comments, returned, attrs):
    """An input named like a previous value (x_prev, x_old, last_x, ...) whose next value is
    returned (a key in `returned`) or stored as an attribute (a name in `attrs`) as x_next,
    next_x, x_new, new_x or x is a state."""
    inputs = data.get("inputs", {})
    for name in list(inputs):
        base = _state_base(name)
        if base is None:
            continue
        for candidate in (f"{base}_next", f"next_{base}", f"{base}_new", f"new_{base}", base):
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


def _property_values(obj, arrays=False, everything=False):
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
        except Exception as e:
            if everything:   # the exception, in place of the value
                values[name] = e
            continue
        if everything or _fmi_value(value, arrays):
            values[name] = _snapshot(value)
    return values


def _writable_attribute(obj, name):
    if name not in getattr(obj, "__dict__", {}):
        prop = inspect.getattr_static(type(obj), name, None)
        return isinstance(prop, property) and prop.fset is not None
    return True
