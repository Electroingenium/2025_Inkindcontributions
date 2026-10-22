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

#: Step size (and end time) passed to a probe call's time arguments.
PROBE_STEP_SIZE = 1.0

def _run_setup(data, obj=None):
    """Run ``[model] setup`` steps for the probe: functions before construction, methods after.

    The same order as :meth:`Engine._run_setup`, so the probe sees the model as the FMU will.

    :param data: the config being inferred; updated in place.
    :type data: dict
    :param obj: the constructed object (runs the method steps), or None (runs the function steps).
    """
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
    """``--probe`` for a class: construct the object, call the step method once, and read what changed.

    Outputs come from the return value, from properties, from GEKKO results and from numeric
    attributes the step set (new: outputs) or changed (existing: locals). Also decides
    ``init_call`` (a step that changes nothing can run at initialization) and ``save_state``
    (:func:`_check_picklable`). A failing construction or call is noted and falls back to reading
    the code.

    :param cls: the model class (None for a factory function).
    :type cls: type or None
    :param method_name: the step method.
    :type method_name: str
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :param call_starts: ``--start`` values for the step method's arguments.
    :type call_starts: dict
    :param create: a classmethod that builds the object (``--create``), or None.
    :type create: str or None
    :param factory: a factory function that builds the object, or None.
    :type factory: callable or None
    :param converts: ``--convert`` options.
    :type converts: dict
    :return: ``(object or None, returned keys, attribute names seen)``.
    :rtype: tuple
    :raises ConstantError: a configured constant can't be computed.
    :raises InterfaceError: the factory's object has no such method.
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
            _arguments(getattr(cls, method_name), "inputs", data, comments,
                       skip_self=not data["model"].get("call_on_class"),
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

    _arguments(method, "inputs", data, comments, skip_self=not factory and not data["model"].get("call_on_class"),
               constants_key="call_constants",
               arrays=arrays, starts=call_starts)
    _apply_converts(data, converts)
    before, state_before = _numeric_attributes(obj, arrays), _state_bytes(obj)
    try:
        result = _probe_call(_step_method(obj, method_name, data), data, comments, constants_key="call_constants")
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
    if "outputs" not in data and data.get("locals"):
        # nothing else to read: what the step changes is its result (river's intercept)
        data["outputs"] = data.pop("locals")
        for attr in data["outputs"]:
            comments[("outputs", attr)] = f"changed by {method_name}(); an output, since the probe found no other"
            comments.pop(("locals", attr), None)
    _check_sizes(obj, method_name, data, comments)
    return obj, returned, set(getattr(obj, "__dict__", {})) | set(_property_values(obj, arrays)) | unfit


#: GEKKO classes that hold solved results: Var/SV/CV, Intermediate, FV/MV (not Param, Const).
GEKKO_RESULTS = ("GKVariable", "GK_Intermediate", "GK_FV")   # Var/SV/CV, Intermediate, FV/MV (not Param, Const)


def _gekko_result(value):
    """The value of a solved GEKKO variable, intermediate, FV or MV at the end of its time horizon.

    GEKKO keeps results in these objects, as ``x.value`` after ``m.solve()``; recognised by module
    and class name, without importing gekko.

    :param value: any attribute value.
    :return: the last value of ``value.value``, or None.
    """
    if not type(value).__module__.startswith("gekko.") \
            or not any(k.__name__ in GEKKO_RESULTS for k in type(value).__mro__):
        return None
    try:
        last = value.value[-1]
    except Exception:   # not solved yet: a single value
        return None
    return last if _fmi_value(last) else None


def _gekko_outputs(obj, data, comments, taken):
    """Outputs for the object's attributes that hold GEKKO results.

    ``self.X = m.Var(...)`` and dicts of them (``self.W = {"HOU1": m.Var(...)}``), read as their
    last value (``from = "attr:X.value.-1"``).

    :param obj: the model object.
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param taken: names already used.
    :type taken: set[str]
    :return: the names added.
    :rtype: set[str]
    """
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
    """Commented-out entries for properties annotated as a number, bool or str whose probe value isn't one.

    The code alone would make them outputs, but in the probe they were e.g. None, or raised.

    :param obj: the model object.
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :param taken: names already used.
    :type taken: set[str]
    :return: their names.
    :rtype: set[str]
    """
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
    """Call the step method a second time and drop arrays whose size changed.

    An array whose size changes (a history that grows each call) can't be an FMI array, which
    has a fixed size.

    :param obj: the model object.
    :param method_name: the step method.
    :type method_name: str
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    """
    sized = [(section, name, info) for section in ("outputs", "locals")
             for name, info in data.get(section, {}).items() if "dimensions" in info]
    if not sized:
        return
    from fmugen.templates.fmugen_runtime import get_path, pick
    try:
        result = _call_with_probe_inputs(_step_method(obj, method_name, data), data, "call_constants")
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
    """Names already used by variables of any section.

    :param data: the config being inferred; updated in place.
    :type data: dict
    :rtype: set[str]
    """
    return {n for section in ("parameters", "structural_parameters", "inputs", "states", "outputs", "locals")
            for n in data.get(section, {})}


def _add_returned(read, data, comments, is_class, arrays, probe, seen):
    """Outputs from what the code returns (:func:`static.returned`).

    With ``--probe``, only ones the probe didn't see; results of unknown type are added as
    guesses, and ones that may be None are commented out.

    :param read: what the code returns.
    :type read: static.Returned
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param is_class: whether the model is a class (``from`` is then always written).
    :type is_class: bool
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :param probe: whether ``--probe`` is in effect.
    :type probe: bool
    :param seen: names the probe already handled.
    :type seen: set[str]
    """
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
    """Outputs and locals from the attributes the step method assigns, and the object's own properties.

    Attributes also set in ``__init__`` become locals (they exist before the first step), the
    others outputs. Unannotated properties are only suggested: reading them would run code.

    :param cls: the model class.
    :type cls: type
    :param method_name: the step method.
    :type method_name: str
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :param probe: whether ``--probe`` is in effect.
    :type probe: bool
    :param seen: names the probe already handled.
    :type seen: set[str]
    """
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

#: Converters tried in order when a probe call fails with list inputs.
ARRAY_RETRIES = ("numpy", "torch:tensor")   # tried in order when a probe call fails with list inputs


def _probe_constants(data, table, positional=False):
    """Constants set in the config (e.g. computed by a call), resolved as the FMU would.

    :param data: the config being inferred; updated in place.
    :type data: dict
    :param table: ``"constants"`` or ``"call_constants"``.
    :type table: str
    :param positional: return ``{position: value}`` of those named ``"0"``, ``"1"``, ... (passed to
        ``*args``) instead of the keyword ones.
    :type positional: bool
    :return: name (or position) -> value.
    :rtype: dict
    :raises ConstantError: a constant fails to compute.
    """
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
    """A constant (e.g. ``--start NAME=call:...``) that can't be computed: the FMU would fail the same way.

    Re-raised instead of being turned into a comment, because no config could fix it.
    """


def _probe_call(fn, data, comments, constants_key="constants"):
    """Call ``fn`` with the probe inputs (see :func:`_probe_once`), checking date-time guesses.

    Arguments taken as date-times only by their name are checked: the call is also made with the
    number 0.0 there. Works only as a date-time: confirmed; only as a number: an ordinary input
    instead; both or neither: left as a guess.

    :param fn: the function or bound step method.
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param constants_key: the constants table passed with the call.
    :type constants_key: str
    :return: what ``fn`` returned.
    :raises Exception: what the call raised.
    """
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
    """Call ``fn`` once with the inferred inputs, time arguments and constants.

    :param fn: the function or bound step method.
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param constants_key: the constants table passed with the call.
    :type constants_key: str
    :return: what ``fn`` returned.
    """
    args, kwargs = _probe_args(data, ("inputs",), fn, constants_key)
    kwargs.update(_time_kwargs(data.get("time", {})))
    kwargs.update(_probe_constants(data, constants_key))
    from fmugen.templates.fmugen_runtime import results_of
    return results_of(fn(*args, **kwargs))


def _probe_once(fn, data, comments, constants_key="constants"):
    """Call ``fn`` with the probe inputs, retrying in forms the model may need.

    If it fails: with naive date-time epochs, retry them in UTC; with array inputs that are plain
    lists, retry as numpy arrays, then torch tensors (when installed); with scalar inputs, retry
    as one-element numpy arrays. The first form that works is kept in ``data`` with a comment.

    :param fn: the function or bound step method.
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param constants_key: the constants table passed with the call.
    :type constants_key: str
    :return: what ``fn`` returned.
    :raises Exception: the original error, when no retry works.
    """
    def call():
        """One probe call with the current inputs.

        :return: what ``fn`` returned.
        """
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
                result = _retry_as_series(call, data, comments)
            if result is _FAILED:
                result = _retry_as_pint(call, data, comments)
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


#: Sentinel: :func:`_retry_as_arrays` found no call that works.
_FAILED = object()


def _retry_as_arrays(call, data, comments):
    """Call again with each number input as a one-element numpy array (``convert = "numpy:atleast_1d"``).

    Some libraries take only arrays (thermofeel's calculate_heat_index_simplified calls
    numpy.nonzero on its inputs).

    :param call: makes the probe call.
    :type call: callable
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :return: the result, or :data:`_FAILED`.
    """
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

def _retry_as_series(call, data, comments):
    """Call again with each number input as a one-value pandas Series indexed by a date (``convert = "series"``).

    Some libraries read the date from their inputs' index (pyet's ``pm_fao56`` takes the day of
    the year from ``rs.index``). The epoch is today at 00:00, as for date-time arguments.

    :param call: makes the probe call.
    :type call: callable
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :return: the result, or :data:`_FAILED`.
    """
    numbers = {name: info for name, info in data.get("inputs", {}).items()
               if isinstance(info.get("start"), (int, float)) and not isinstance(info.get("start"), bool)
               and "dimensions" not in info and not info.get("convert") and not info.get("numpy")}
    if not numbers or importlib.util.find_spec("pandas") is None:
        return _FAILED
    epoch = datetime.datetime.combine(datetime.date.today(), datetime.time()).isoformat()
    for info in numbers.values():
        info.update({"convert": "series", "epoch": epoch})
    try:
        result = call()
    except Exception:
        for info in numbers.values():
            del info["convert"], info["epoch"]
        return _FAILED
    for name in numbers:
        comments[("inputs", name)] = ("passed as a pandas Series dated epoch + t: the probe failed with plain numbers "
                                      "and arrays; set the epoch you need")
    return result


#: pint base dimension -> its SI unit, for an argument whose error names only its dimension (metpy).
PINT_BASE_UNITS = {"[length]": "m", "[mass]": "kg", "[time]": "s", "[temperature]": "K", "[current]": "A",
                   "[substance]": "mol", "[luminosity]": "cd", "dimensionless": "dimensionless"}


def _pint_unit(message, numbers):
    """The input a pint unit error is about, and the unit it asks for; or None.

    Reads fluids.units' ``Converting 2.5 dimensionless to units of m/s`` (the input is found by
    its value) and metpy's ``temperature requires "[temperature]"`` (the name in backquotes) (a dimension, given its SI
    unit: K).

    :param message: the error message.
    :type message: str
    :param numbers: ``{name: info}`` of the inputs still dimensionless.
    :type numbers: dict
    :rtype: tuple[str, str] or None
    """
    import re
    match = re.search(r"Converting (\S+) dimensionless to units of (\S+)", message)
    if match:
        try:
            value = float(match[1])
        except ValueError:
            return None
        names = [n for n, info in numbers.items() if float(info["start"]) == value]
        return (names[0], match[2].rstrip(".,")) if len(names) == 1 else None
    match = re.search(r"`(\w+)` requires \"([^\"]+)\"", message)
    if match and match[1] in numbers:
        unit = match[2]
        for dimension, base in PINT_BASE_UNITS.items():
            unit = unit.replace(dimension, base)
        return (match[1], unit) if "[" not in unit else None
    return None


def _retry_as_pint(call, data, comments):
    """Call again with each number input as a pint quantity (``convert = "pint"``), learning units from the errors.

    Libraries that check units (fluids.units, metpy) refuse plain numbers. Every number input
    starts dimensionless; each error that names an input's unit sets it, until the call works.
    The start values are taken as being in those units.

    :param call: makes the probe call.
    :type call: callable
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :return: the result, or :data:`_FAILED`.
    """
    numbers = {name: info for name, info in data.get("inputs", {}).items()
               if isinstance(info.get("start"), (int, float)) and not isinstance(info.get("start"), bool)
               and "dimensions" not in info and not info.get("convert") and not info.get("numpy")}
    if not numbers or importlib.util.find_spec("pint") is None:
        return _FAILED
    for info in numbers.values():
        info.update({"convert": "pint", "unit": "dimensionless"})
    pending = dict(numbers)
    for _ in range(len(numbers) + 1):
        try:
            result = call()
        except Exception as e:
            found = _pint_unit(str(e), pending)
            if found is None:
                break
            name, unit = found
            pending.pop(name)["unit"] = unit
            continue
        for name in numbers:
            comments[("inputs", name)] = ("passed as a pint quantity: the probe failed with plain numbers; the unit is "
                                          "the one the model asked for, so check the start is in it")
        return result
    for info in numbers.values():
        del info["convert"], info["unit"]
    return _FAILED


def _state_bytes(obj):
    """The object's attributes pickled, to tell whether a call changed them.

    :param obj: the model object.
    :return: the pickle, or None if they can't be pickled.
    :rtype: bytes or None
    """
    try:
        return pickle.dumps(vars(obj))
    except Exception:
        return None


def _check_picklable(obj, data, comments):
    """Pick ``[model] save_state`` by trying to pickle the object as the runtime would.

    FMU state save/restore pickles the model object (pickle, else cloudpickle). If that fails,
    save only the attributes that can be pickled; if none can, declare save/restore unsupported.

    :param obj: the model object.
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    """
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

def _step_method(obj, method_name, data):
    """The step method to call: bound to ``obj``, or taken from its class with ``call_on_class``.

    :param obj: the model object.
    :param method_name: the step method.
    :type method_name: str
    :param data: the config being inferred.
    :type data: dict
    :rtype: callable
    """
    return getattr(type(obj) if data["model"].get("call_on_class") else obj, method_name)


def _varargs_by_keyword(constructor, init_starts, data, probe):
    """Whether a ``(*args, **kwargs)`` constructor needs its ``--start`` values as keywords.

    The signature can't tell: ``StateSpace(A, B, C, D)`` takes them by position,
    ``Quaternion(axis=..., angle=...)`` by keyword. Without ``--probe`` they go by position.
    With it, by keyword only when the positional call fails and the keyword one works.

    :param constructor: the class (or ``create`` classmethod).
    :param init_starts: the values given to the constructor.
    :type init_starts: dict
    :param data: the config being inferred (for its setup calls).
    :type data: dict
    :param probe: whether ``--probe`` is in effect.
    :type probe: bool
    :rtype: bool
    """
    try:
        params = inspect.signature(constructor).parameters.values()
    except (TypeError, ValueError):
        return False
    if not probe or not init_starts or not any(p.kind is p.VAR_KEYWORD for p in params) \
            or not any(p.kind is p.VAR_POSITIONAL for p in params):
        return False
    from fmugen.templates.fmugen_runtime import resolve_constant
    try:
        _run_setup(data)
        values = {n: resolve_constant(v) for n, v in init_starts.items()}
    except Exception:
        return False
    try:
        constructor(*values.values())
        return False
    except Exception:
        pass
    try:
        constructor(**values)
    except Exception:
        return False
    return True


def _split_varargs(cls, create, method_name, init_starts, call_starts, data, comments, probe):
    """Split ``--start`` values between a constructor and a step method that both take only ``*args``.

    SWIG classes such as ``openturns.Normal(mu, sigma).computePDF(x)``: the signatures can't tell
    which values go where, so _assign_starts gives them all to the constructor. With ``--probe``,
    the first values (in ``--start`` order) go to the constructor, the rest to the method, trying
    the constructor with as many as possible first, and the first split where both calls work
    is kept.

    :param cls: the model class.
    :type cls: type
    :param create: ``--create``, or None (then nothing is split).
    :type create: str or None
    :param method_name: the step method.
    :type method_name: str
    :param init_starts: the values given to the constructor so far.
    :type init_starts: dict
    :param call_starts: the values given to the method so far.
    :type call_starts: dict
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param probe: whether ``--probe`` is in effect.
    :type probe: bool
    :return: ``(constructor starts, method starts)``.
    :rtype: tuple[dict, dict]
    """
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
    """Positional and keyword arguments for a probe call from the inferred start values.

    Includes the positional constants of ``constants_key``; item and field bindings
    (``arg:pair[0]``, ``arg:u.T``) are assembled as the runtime does (:func:`assemble_items`).

    :param data: the config being inferred; updated in place.
    :type data: dict
    :param sections: the variable sections passed (``("inputs",)`` or ``("parameters",)``).
    :type sections: tuple[str, ...]
    :param fn: the function called (to build object arguments).
    :type fn: callable or None
    :param constants_key: the constants table for positional constants, or None.
    :type constants_key: str or None
    :return: ``(args, kwargs)``.
    :rtype: tuple[list, dict]
    """
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
    """Python values of the start values of these sections, as the runtime would pass them.

    Enum members, reshaped (numpy) arrays, Binary bytes and ``convert`` functions are applied.

    :param data: the config being inferred; updated in place.
    :type data: dict
    :param sections: the variable sections.
    :type sections: tuple[str, ...]
    :return: variable name -> value.
    :rtype: dict
    """
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
            if info.get("convert") in ("series", "pint"):   # dated at the epoch, as at time 0; in the unit
                from fmugen.templates.fmugen_runtime import converter
                kwargs[name] = converter(info)(kwargs[name])
            elif info.get("convert"):
                kwargs[name] = resolve_reference(info["convert"])(kwargs[name])
    return kwargs


def _time_kwargs(time_args):
    """Values of the ``[time]`` arguments for a probe call.

    Date-times get their epoch; ``step_size`` and ``end_time`` get :data:`PROBE_STEP_SIZE`;
    everything else 0.0.

    :param time_args: the ``[time]`` table.
    :type time_args: dict
    :rtype: dict
    """
    kwargs = {}
    for arg, source in time_args.items():
        if isinstance(source, dict):   # { source = ..., epoch = ... }: a date-time
            kwargs[arg] = datetime.datetime.fromisoformat(source["epoch"])
        else:
            kwargs[arg] = {"step_size": PROBE_STEP_SIZE, "end_time": PROBE_STEP_SIZE}.get(source, 0.0)
    return kwargs

def _outputs_from_return(result, data, comments, default_name, is_class, arrays=False):
    """Outputs from a probe result.

    Dicts, pandas/xarray tables, NamedTuples, tuples/lists, single values and objects (their
    public attributes and properties) are split into outputs; nested ones get dotted names.

    :param result: what the probe call returned.
    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param default_name: name of a single result, and prefix of tuple positions (``y0``, ``y1``).
    :type default_name: str
    :param is_class: whether the model is a class.
    :type is_class: bool
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :return: the names of the parts it looked at (dict keys, tuple positions y0, y1, ...), also
        those left out because they aren't FMI values.
    :rtype: set[str]
    """
    outputs = data.setdefault("outputs", {})
    wrapped = any(info.get("convert") == "numpy:atleast_1d" for info in data.get("inputs", {}).values())
    if wrapped and getattr(result, "size", None) == 1 and hasattr(result, "reshape"):
        result = result.reshape(())[()]   # numbers passed as one-element arrays: a number comes back as one
    parts = set()   # properties of a returned object, which may share a name with an input (ufloat's nominal_value)
    if isinstance(result, Mapping):
        items = [(str(k), v, f"return:{k}") for k, v in result.items()]
    elif _table_children(result) == [] and getattr(result, "size", None) == 1:
        items = [(default_name, result.item(), "return")]   # one value labelled by a date (pyet): read as a number
    elif _table_children(result) is not None:   # pandas Series / one-row DataFrame, xarray Dataset
        items = [(k, v, f"return:{k}") for k, v in _table_children(result)]
    elif arrays and _array_info(result):
        items = [(default_name, result, "return")]
    elif isinstance(result, tuple) and hasattr(result, "_fields"):   # NamedTuple: use the field names
        items = [(field, getattr(result, field), f"return:{field}") for field in result._fields]
    elif isinstance(result, (tuple, list)):
        items = [leaf for i, v in enumerate(result) for leaf in _positions(f"{default_name}{i}", v, f"return:{i}", arrays)]
    elif _fmi_value(result) or (result is not None and _misfit(result)):
        items = [(default_name, result, "return")]
    elif result is not None and (hasattr(result, "__dict__") or _public_properties(result, arrays=True)):
        # an object: its public attributes and properties, e.g. uncertainties' nominal_value, std_dev
        public = {k: v for k, v in getattr(result, "__dict__", {}).items() if not k.startswith("_")}
        public.update({k: v for k, v in _public_properties(result, arrays=True).items() if k not in public})
        items = [_single(k, v, f"return:{k}") for k, v in public.items()]
        parts = set(public) - set(getattr(result, "__dict__", {}))   # computed, not a stored copy of an input
    else:
        items = []
    looked_at = {name for name, _, _ in items}
    items = [leaf for name, value, source in items for leaf in _nested(name, value, source, arrays)]
    items = [part for item in items for part in _complex_parts(*item)]
    # keys that aren't names (radioactivedecay's "N-14"): a valid name, the real key kept in `from`
    items = [(_valid_name(name), value, source) for name, value, source in items]
    taken = {n for section in ("parameters", "inputs", "states") for n in data.get(section, {})}
    for name, value, source in items:
        if name in taken and name in parts and not is_class:
            # a property of the object a function returns, named like an input: y_nominal_value
            # (a class's step that echoes its input, as pyfluids' with_state, still gives none)
            name = f"{default_name}_{name}"
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


def _complex_parts(name, value, source):
    """A complex result as two outputs, its real and imaginary parts (FMI has no complex type).

    ``y`` read from ``return`` gives ``y_real`` (``return:real``) and ``y_imag``; anything else
    is returned as it is.

    :param name: the output name.
    :type name: str
    :param value: its probe value.
    :param source: its ``from`` binding.
    :type source: str
    :rtype: list[tuple]
    """
    scalar = _scalar_of(value)
    if not (isinstance(scalar, complex) or "complex" in str(getattr(value, "dtype", ""))):
        return [(name, value, source)]
    sep = "." if ":" in source else ":"
    return [(f"{name}_{part}", getattr(value, part), f"{source}{sep}{part}") for part in ("real", "imag")]


#: How deep nested results are split into dotted outputs.
MAX_NESTING = 4


def _nested(name, value, source, arrays, depth=0):
    """``(name, value, source)`` for each value inside nested dicts, NamedTuples, dataclasses and namespaces.

    Named with dots: ``{"zone": {"T": 21}}`` gives ``("zone.T", 21, "return:zone.T")``.

    :param name: the outer name.
    :type name: str
    :param value: the value.
    :param source: its ``from`` binding.
    :type source: str
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :param depth: the current nesting level.
    :type depth: int
    :rtype: list[tuple]
    """
    if depth < MAX_NESTING and not _fmi_value(value, arrays):
        children = _children(value)
        if children:
            sep = ":" if source == "return" else "."
            return [leaf for key, child in children
                    for leaf in _nested(f"{name}.{key}", child, f"{source}{sep}{key}", arrays, depth + 1)]
    return [(name, value, source)]


def _positions(name, value, source, arrays, depth=0):
    """``(name, value, source)`` for each item of tuples nested in a tuple result, which would be skipped whole.

    nashpy's ``support_enumeration`` gives ``((sigma_r, sigma_c), ...)``: ``y0`` becomes ``y0_0``
    (``return:0.0``) and ``y0_1``. Only plain tuples are split, and only when they aren't an FMI
    value themselves (a tuple of numbers stays one array).

    :param name: the variable name of ``value``.
    :type name: str
    :param value: an item of the result.
    :param source: its ``from`` binding.
    :type source: str
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :param depth: the current nesting level.
    :type depth: int
    :rtype: list[tuple]
    """
    if depth < MAX_NESTING and type(value) is tuple and value and not _fmi_value(value, arrays):
        return [leaf for i, v in enumerate(value)
                for leaf in _positions(f"{name}_{i}", v, f"{source}.{i}", arrays, depth + 1)]
    return [(name, value, source)]


def _children(value):
    """The named parts of a container value (tables, mappings, NamedTuples, dataclasses, namespaces).

    :param value: the value.
    :return: ``[(name, part)]``, empty for anything else.
    :rtype: list[tuple]
    """
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
    """``[(label, scalar)]`` for a pandas Series, a one-row DataFrame or an xarray Dataset of single values.

    Recognised by module and class name, so pandas/xarray aren't imported; only string labels.

    :param value: the value.
    :return: the pairs, or None for anything else.
    :rtype: list[tuple] or None
    """
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


def _single(name, value, source):
    """A one-element array read as its element: ambiance's properties are ``array([288.15])``.

    :param name: the output name.
    :type name: str
    :param value: its probe value.
    :param source: its ``from`` binding.
    :type source: str
    :return: ``(name, value, source)``, with ``value[0]`` and ``source.0`` for a one-element array.
    :rtype: tuple
    """
    if getattr(value, "ndim", 0) == 1 and getattr(value, "size", 0) == 1:
        return name, value[0], f"{source}.0"
    return name, value, source


def _public_properties(obj, arrays=False):
    """``{name: value}`` of the public properties of obj's class whose value is an FMI value.

    Of properties that are the same object under several names (uncertainties' n and
    nominal_value), only the longest name. The class is searched with
    :func:`inspect.getattr_static`: getattr on the class runs descriptors, which can fail.

    :param obj: the object.
    :param arrays: also numeric arrays.
    :type arrays: bool
    :rtype: dict
    """
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
        if _fmi_value(value, arrays):
            values[name] = value
    return values

def _detect_states(data, comments, returned, attrs):
    """Turn inputs named like a previous value into states.

    An input named like a previous value (x_prev, x_old, last_x, ...) whose next value is
    returned or stored as an attribute as x_next, next_x, x_new, new_x or x is a state, with
    ``next`` bound to that value.

    :param data: the config being inferred; updated in place.
    :type data: dict
    :param comments: ``(section, key) -> text`` for :func:`render_toml`; updated in place.
    :type comments: dict
    :param returned: keys of the return value.
    :type returned: set[str]
    :param attrs: attribute names of the object.
    :type attrs: set[str]
    """
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
    """Snapshots of the object's public attributes that hold FMI values.

    :param obj: the model object.
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :rtype: dict
    """
    try:
        attrs = vars(obj)
    except TypeError:
        return {}
    return {k: _snapshot(v) for k, v in attrs.items() if not k.startswith("_") and _fmi_value(v, arrays)}


def _snapshot(value):
    """A copy that later in-place changes (e.g. numpy ``+=``) don't affect.

    :param value: the value.
    """
    return value.copy() if hasattr(value, "copy") and not isinstance(value, (str, bytes)) else value


def _property_values(obj, arrays=False, everything=False):
    """Public properties of the object whose current value is an FMI value.

    Only properties defined in the model's own package count: base classes from frameworks
    (torch.nn.Module, transformers' PreTrainedModel, ...) add properties that aren't model results.

    :param obj: the model object.
    :param arrays: whether arrays may be FMU variables (FMI 3).
    :type arrays: bool
    :param everything: include every property, with the exception in place of the value when
        reading it raised.
    :type everything: bool
    :rtype: dict
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
    """Whether ``name`` can be set on the object: an instance attribute, or a property with a setter.

    :param obj: the model object.
    :param name: the attribute.
    :type name: str
    :rtype: bool
    """
    if name not in getattr(obj, "__dict__", {}):
        prop = inspect.getattr_static(type(obj), name, None)
        return isinstance(prop, property) and prop.fset is not None
    return True
