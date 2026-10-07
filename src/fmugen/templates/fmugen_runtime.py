"""fmugen runtime engine, shared by the FMI 2 and FMI 3 adapters (resources/model.py).

This file is identical for every model and every FMI version. It reads
resources/interface.json, imports the user's code (resources/fmugen_model/) and runs it: constructing the model
object, calling it once per step or per clock tick, and moving values between FMU
variables and the arguments, return values and attributes of the user's code.

The user's code is never modified. The FMI-version-specific adapters translate
FMI calls into the methods of `Engine`.
"""
import ast
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
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path

DEFAULT_VALUES = {
    "Real": 0.0, "Float32": 0.0, "Float64": 0.0,
    "Integer": 0, "Int8": 0, "UInt8": 0, "Int16": 0, "UInt16": 0,
    "Int32": 0, "UInt32": 0, "Int64": 0, "UInt64": 0,
    "Boolean": False, "String": "", "Binary": b"", "Enumeration": 1,
}
INT_RANGES = {
    "Int8": (-2**7, 2**7 - 1), "UInt8": (0, 2**8 - 1),
    "Int16": (-2**15, 2**15 - 1), "UInt16": (0, 2**16 - 1),
    "Int32": (-2**31, 2**31 - 1), "UInt32": (0, 2**32 - 1),
    "Int64": (-2**63, 2**63 - 1), "UInt64": (0, 2**64 - 1),
    "Integer": (-2**31, 2**31 - 1),
}
FLOAT_TYPES = ("Real", "Float32", "Float64")
TRUE_STRINGS = ("true", "1", "yes", "on")
FALSE_STRINGS = ("false", "0", "no", "off", "")

# Interval qualifiers (FMI 3)
INTERVAL_NOT_YET_KNOWN, INTERVAL_UNCHANGED, INTERVAL_CHANGED = 0, 1, 2


class Status:
    """FMI status codes; identical numbering in FMI 2 and FMI 3."""
    ok = 0
    warning = 1
    discard = 2
    error = 3
    fatal = 4


class Engine:
    def __init__(self, resources_dir, log, info_category="logAll"):
        """`log(message, status, category)` forwards a message to the importer."""
        self.resources_dir = Path(resources_dir)
        self.log = log
        self.info_category = info_category
        self.interface = json.loads((self.resources_dir / "interface.json").read_text())
        self._output, self._position = _capture_output(self.interface.get("capture_output", False)), 0
        self.variables = self.interface["variables"]
        self.by_name = {v["name"]: v for v in self.variables}
        self.by_reference = {v["valueReference"]: v for v in self.variables}
        # FMI 2 has no arrays: element k of an array has its own reference, the array's + k
        self.elements = {} if self.interface.get("fmi_version") != 2 else {
            v["valueReference"] + k: (v, k) for v in self.variables if v.get("dimensions")
            for k in range(math.prod(v["dimensions"]))}
        self.clocks = {c["name"]: c for c in self.interface.get("clocks", [])}
        self.clock_by_reference = {c["valueReference"]: c for c in self.clocks.values()}
        self.events = self.interface.get("events", {})
        self.experiment = self.interface.get("experiment", {})

        self.logging_on = True
        hf_cache = self.resources_dir / "hf_cache"
        if hf_cache.is_dir():   # Hugging Face models bundled by fmugen build: load them from the FMU, offline
            os.environ.update(HF_HUB_CACHE=str(hf_cache), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        cwd = self.interface.get("cwd")
        self.cwd = self.resources_dir / cwd if cwd is not None else None
        with self._in_model_dir():   # the model may read files when it is imported
            self.module, self.entry = load_entry(self.interface, self.resources_dir)
            self.enums = {
                name: resolve_reference(td["enum"])
                for name, td in self.interface.get("type_definitions", {}).items() if td.get("enum")
            }
            self.constants = {k: resolve_constant(v) for k, v in self.interface.get("constants", {}).items()}
            self.call_constants = {k: resolve_constant(v)
                                   for k, v in self.interface.get("call_constants", {}).items()}
            self.converters = {v["name"]: converter(v) for v in self.variables if v.get("convert")}
            # [model] globals: module-level state, put back to its import-time value on reset
            self.globals = [split_global(ref) for ref in self.interface.get("globals", [])]
            self.global_starts = copy.deepcopy(self._read_globals())
        self.is_class = self.interface["entry"]["kind"] == "class"
        self.reset()
        self._forward_output()   # e.g. warnings printed while the model was imported

    # ================= life cycle =================

    def reset(self):
        if getattr(self, "global_starts", None):
            self._write_globals(copy.deepcopy(self.global_starts))
        self.values = {}
        for v in self.variables:
            if v["causality"] != "independent" and not v.get("dimensions"):
                self.values[v["name"]] = self._start(v)
        for v in self.variables:  # arrays last: their sizes may depend on structural parameters
            if v.get("dimensions"):
                self.values[v["name"]] = self._start(v)
        self.obj = None
        self.mode = "instantiated"
        self.time = self.experiment.get("start_time", 0.0)
        self.start_time, self.stop_time, self.tolerance = self.time, None, None
        self.clock_active = {name: False for name in self.clocks}
        self.clock_interval = {name: c.get("interval") for name, c in self.clocks.items()}
        self.clock_shift = {name: c.get("shift", 0.0) for name, c in self.clocks.items()}
        self.interval_reported = {}
        self.clocks_handled = set()
        self.clock_last_tick = {}
        self.terminate_requested = False
        self.next_event_time = None
        return Status.ok

    def setup_experiment(self, start_time, stop_time=None, tolerance=None):
        self.time = start_time
        self.start_time, self.stop_time, self.tolerance = start_time, stop_time, tolerance
        return Status.ok

    def enter_initialization_mode(self):
        self.mode = "initialization"
        return Status.ok

    def exit_initialization_mode(self, next_mode="step"):
        def initialize():
            self._run_setup(after_construction=False)
            if self.is_class:
                kwargs = dict(self.constants)
                kwargs.update(self._bound("init"))
                create = self.interface["entry"].get("create")
                self.obj = (getattr(self.entry, create) if create else self.entry)(**kwargs)
                self._run_setup(after_construction=True)
                self._apply_attributes(clock=None)
                for name in self.clocks:
                    self._apply_attributes(clock=name)
            if self.interface["entry"].get("init_call"):
                result = self._call(self.time, self.experiment.get("step_size", 0.0))
                self._read_results(result, have_result=True, update_states=False, missing_ok=True)
            else:
                self._read_results(None, have_result=False, update_states=False, missing_ok=True)
            for name, clock in self.clocks.items():
                if clock["causality"] == "input":
                    self._read_results(None, have_result=False, update_states=False, missing_ok=True, clock=name)

        status = self.run("initialization", initialize)
        if status == Status.ok:
            self.mode = next_mode
        return status

    def do_step(self, current_time, step_size):
        """Return (status, event_handling_needed)."""
        if self.mode != "step":
            return self.error(f"doStep called in mode {self.mode!r}"), False
        fixed = self.experiment.get("step_size") if self.experiment.get("fixed_step") else None
        if fixed is not None and not math.isclose(step_size, fixed, rel_tol=1e-9, abs_tol=1e-12):
            return self.error(f"this FMU only supports a communication step size of {fixed}, got {step_size}"), False

        ticked = []

        def advance():
            if self.interface["entry"].get("step", True):
                result, have_result = self._call(current_time, step_size), True
                self._read_results(result, have_result=True, update_states=True, missing_ok=False)
            else:  # [model] call = false: only clocks run code
                result, have_result = None, False
                self._read_results(None, have_result=False, update_states=False, missing_ok=True)
            ticked.extend(self._check_output_clocks(result, have_result=have_result))
            self._check_events(result, have_result=have_result)

        status = self.run("doStep", advance)
        if status == Status.ok:
            self.time = current_time + step_size
        return status, bool(ticked)

    def terminate(self):
        method = self.interface["entry"].get("terminate")
        status = Status.ok
        if method and self.obj is not None:
            status = self.run("terminate", lambda: getattr(self.obj, method)())
        self.mode = "terminated"
        return status

    # ================= FMI 3 modes =================

    def enter_configuration_mode(self):
        if not any(v["causality"] == "structuralParameter" for v in self.variables):
            return self.error("this FMU has no structural parameters")
        if self.mode == "instantiated":
            self.mode = "configuration"
        elif self.mode == "step":
            self.mode = "reconfiguration"
        else:
            return self.error(f"cannot enter configuration mode from mode {self.mode!r}")
        return Status.ok

    def exit_configuration_mode(self):
        if self.mode == "configuration":
            self.mode = "instantiated"
        elif self.mode == "reconfiguration":
            self.mode = "step"
        else:
            return self.error(f"not in configuration mode (mode {self.mode!r})")
        return Status.ok

    def enter_event_mode(self):
        self.mode = "event"
        self.clocks_handled = set()
        return Status.ok

    def enter_step_mode(self):
        self.mode = "step"
        for name in self.clock_active:
            self.clock_active[name] = False
        return Status.ok

    def update_discrete_states(self):
        """Run the code of every active input clock that hasn't run in this event yet.

        Return (status, terminate_simulation, next_event_time or None).
        """
        def update():
            for name, clock in self.clocks.items():
                if clock["causality"] != "input" or not self.clock_active[name] or name in self.clocks_handled:
                    continue
                self.clocks_handled.add(name)
                if not clock.get("call"):
                    continue
                # step size of a clock call: time since this clock last ticked (its interval the first time)
                last = self.clock_last_tick.get(name)
                step_size = self.time - last if last is not None else (self.clock_interval.get(name) or 0.0)
                self.clock_last_tick[name] = self.time
                result = self._call(self.time, step_size, clock=name)
                self._read_results(result, have_result=True, update_states=False, missing_ok=False, clock=name)
                # the clock's code may also have changed attributes behind unclocked outputs
                self._read_results(None, have_result=False, update_states=False, missing_ok=True)
                self._check_output_clocks(result, have_result=True)
                self._check_events(result, have_result=True)
                self._remember_interval(name, result, have_result=True)

        status = self.run("updateDiscreteStates", update)
        return status, self.terminate_requested, self.next_event_time

    # ================= values =================

    def size(self, var):
        """Number of scalar values of a variable (None for a scalar)."""
        dims = var.get("dimensions")
        if not dims:
            return None
        n = 1
        for d in dims:
            n *= int(self.values[d]) if isinstance(d, str) else d
        return n

    def get_values(self, references):
        """Return (status, flat list of values)."""
        values = []
        for r in references:
            if r in self.elements:
                var, k = self.elements[r]
                values.append(self.values[var["name"]][k])
                continue
            var = self.by_reference.get(r)
            if var is None:
                return self.error(f"unknown value reference {r}"), []
            if var["causality"] == "independent":
                values.append(self.time)
            elif var.get("dimensions"):
                values.extend(self.values[var["name"]])
            else:
                values.append(self.values[var["name"]])
        return Status.ok, values

    def set_values(self, references, values):
        values = list(values)
        cursor = 0
        for r in references:
            var, element = self.elements.get(r, (self.by_reference.get(r), None))
            if var is None:
                return self.error(f"unknown value reference {r}")
            n = self.size(var) if element is None else None
            if len(values) - cursor < (n or 1):
                return self.error(f"not enough values for {var['name']}")
            raw = values[cursor:cursor + n] if n is not None else values[cursor]
            cursor += n or 1
            if element is not None:   # one element of an FMI 2 array
                current = self.values[var["name"]]
                raw = [*current[:element], raw, *current[element + 1:]]
            problem = self._settable(var)
            if problem:
                return self.error(f"{var['name']} ({var['causality']}) cannot be set {problem}")
            try:
                value = [coerce(var["type"], x) for x in raw] if isinstance(raw, list) else coerce(var["type"], raw)
            except (TypeError, ValueError) as e:
                return self.error(f"{var['name']}: {e}")
            name = var["name"]
            self.values[name] = value

            if var["causality"] == "structuralParameter":
                self._resize_arrays(name)
            if (self.mode in ("step", "event", "reconfiguration") and self.obj is not None and var.get("attr")
                    and var["causality"] in ("parameter", "structuralParameter")):
                status = self.run(f"setting {name}",
                                  lambda: setattr(self.obj, var["attr"], self._to_python(var, self.values[name])))
                if status != Status.ok:
                    return status
                self.run("updating calculated parameters", self._refresh_calculated_parameters)
        return Status.ok

    def _settable(self, var):
        """Return why `var` can't be set now, or None."""
        causality, mode = var["causality"], self.mode
        initializing = mode in ("instantiated", "initialization", "configuration")
        if causality == "input":
            return None
        if causality == "parameter":
            if initializing or var["variability"] == "tunable":
                return None
            return "after initialization (it is a fixed parameter)"
        if causality == "structuralParameter":
            if mode in ("configuration", "initialization") or (
                    mode == "reconfiguration" and var["variability"] == "tunable"):
                return None
            return "outside configuration mode"
        if causality == "local" and var.get("initial") == "exact" and initializing:
            return None
        return "by the importer" if not initializing else "before initialization"

    def _start(self, var):
        start = var.get("start", DEFAULT_VALUES[var["type"]])
        if var["type"] == "Binary":
            start = [bytes.fromhex(s) for s in start] if isinstance(start, list) else bytes.fromhex(start or "")
        n = self.size(var)
        if n is None:
            return start
        if isinstance(start, list):
            if len(start) == n:
                return list(start)
            if len(start) == 1:
                return start * n
            raise ValueError(f"{var['name']}: start has {len(start)} values, expected {n}")
        return [start] * n

    def _resize_arrays(self, structural_name):
        for v in self.variables:
            if structural_name in (v.get("dimensions") or []):
                try:
                    self.values[v["name"]] = self._start(v)
                except ValueError:
                    default = DEFAULT_VALUES[v["type"]]
                    self.values[v["name"]] = [default] * self.size(v)
                    self.log(f"{v['name']} was reset to {default!r} because {structural_name} changed its size; "
                             "set it before initialization", Status.warning, "logStatusWarning")

    # ================= clocks =================

    def set_clocks(self, references, values):
        for r, value in zip(references, values):
            clock = self.clock_by_reference.get(r)
            if clock is None or clock["causality"] != "input":
                return self.error(f"value reference {r} is not an input clock")
            self.clock_active[clock["name"]] = bool(value)
        return Status.ok

    def get_clocks(self, references):
        values = []
        for r in references:
            clock = self.clock_by_reference.get(r)
            if clock is None:
                return self.error(f"value reference {r} is not a clock"), []
            values.append(self.clock_active[clock["name"]])
            if clock["causality"] == "output":
                self.clock_active[clock["name"]] = False  # output clocks reset once read
        return Status.ok, values

    def get_intervals(self, references):
        """Return (status, intervals, qualifiers)."""
        intervals, qualifiers = [], []
        for r in references:
            clock = self.clock_by_reference.get(r)
            if clock is None:
                return self.error(f"value reference {r} is not a clock"), [], []
            name = clock["name"]
            interval = self.clock_interval.get(name)
            if interval is None:
                intervals.append(0.0)
                qualifiers.append(INTERVAL_NOT_YET_KNOWN)
                continue
            if clock["interval_variability"] in ("changing", "countdown", "tunable"):
                qualifier = INTERVAL_UNCHANGED if self.interval_reported.get(name) == interval else INTERVAL_CHANGED
            else:
                qualifier = INTERVAL_CHANGED if name not in self.interval_reported else INTERVAL_UNCHANGED
            self.interval_reported[name] = interval
            intervals.append(float(interval))
            qualifiers.append(qualifier)
        return Status.ok, intervals, qualifiers

    def set_intervals(self, references, intervals):
        for r, interval in zip(references, intervals):
            clock = self.clock_by_reference.get(r)
            if clock is None:
                return self.error(f"value reference {r} is not a clock")
            variability = clock["interval_variability"]
            allowed = {"fixed": ("instantiated", "initialization"), "tunable": ("instantiated", "initialization", "event")}
            if self.mode not in allowed.get(variability, ()):
                return self.error(f"the interval of {clock['name']} ({variability}) cannot be set in mode {self.mode!r}")
            self.clock_interval[clock["name"]] = float(interval)
        return Status.ok

    def get_shifts(self, references):
        shifts = []
        for r in references:
            clock = self.clock_by_reference.get(r)
            if clock is None:
                return self.error(f"value reference {r} is not a clock"), []
            shifts.append(float(self.clock_shift[clock["name"]]))
        return Status.ok, shifts

    def set_shifts(self, references, shifts):
        for r, shift in zip(references, shifts):
            clock = self.clock_by_reference.get(r)
            if clock is None:
                return self.error(f"value reference {r} is not a clock")
            if clock["interval_variability"] not in ("fixed", "tunable") or self.mode not in ("instantiated", "initialization"):
                return self.error(f"the shift of {clock['name']} cannot be set now")
            self.clock_shift[clock["name"]] = float(shift)
        return Status.ok

    def _check_output_clocks(self, result, have_result):
        """Tick output clocks whose source is truthy; read their clocked variables. Return ticked names."""
        ticked = []
        for name, clock in self.clocks.items():
            if clock["causality"] != "output":
                continue
            found, value = self._source_value(clock["from"], result, have_result, missing_ok=True)
            if found and value:
                self.clock_active[name] = True
                ticked.append(name)
                self._read_results(result, have_result=have_result, update_states=False, missing_ok=False, clock=name)
        return ticked

    def _remember_interval(self, name, result, have_result):
        source = self.clocks[name].get("interval_from")
        if source:
            found, value = self._source_value(source, result, have_result, missing_ok=True)
            if found and value is not None:
                self.clock_interval[name] = float(value)

    def _check_events(self, result, have_result):
        for name, clock in self.clocks.items():
            if clock["causality"] == "input":
                self._remember_interval(name, result, have_result)
        if "terminate" in self.events:
            found, value = self._source_value(self.events["terminate"], result, have_result, missing_ok=True)
            self.terminate_requested = bool(found and value)
        if "next_event_time" in self.events:
            found, value = self._source_value(self.events["next_event_time"], result, have_result, missing_ok=True)
            self.next_event_time = float(value) if found and value is not None else None

    # ================= state =================

    def serialize(self):
        """The FMU state as bytes. [model] save_state = [attributes] saves only those attributes
        of the model object (the rest, e.g. an ONNX session or a device handle, stays as it is)."""
        save = self.interface.get("save_state", True)
        if isinstance(save, list):
            obj = None if self.obj is None else {path: get_path(self.obj, path) for path in save}
        else:
            obj = self.obj
        state = {
            "values": self.values, "obj": obj, "time": self.time, "mode": self.mode,
            "clock_active": self.clock_active, "clock_interval": self.clock_interval,
            "clock_shift": self.clock_shift, "terminate_requested": self.terminate_requested,
            "clock_last_tick": self.clock_last_tick, "globals": self._read_globals(), "rng": rng_states(),
        }
        try:
            return Status.ok, dump_state(state)
        except Exception as e:
            self.log(f"cannot serialize FMU state: {e!r}", Status.error, "logStatusError")
            return Status.error, b""

    def deserialize(self, data):
        try:
            state = load_state(data)
        except Exception as e:
            return self.error(f"cannot deserialize FMU state: {e!r}")
        self.values = dict(state["values"])
        if isinstance(self.interface.get("save_state", True), list):
            if self.obj is not None and state["obj"] is not None:
                for path, value in state["obj"].items():
                    set_path(self.obj, path, value)
        else:
            self.obj = state["obj"]
        self.time, self.mode = state["time"], state["mode"]
        self.clock_active = dict(state.get("clock_active", self.clock_active))
        self.clock_interval = dict(state.get("clock_interval", self.clock_interval))
        self.clock_shift = dict(state.get("clock_shift", self.clock_shift))
        self.terminate_requested = state.get("terminate_requested", False)
        self.clock_last_tick = dict(state.get("clock_last_tick", {}))
        self._write_globals(copy.deepcopy(state.get("globals", {})))
        set_rng_states(state.get("rng", {}))
        return Status.ok

    def _read_globals(self):
        return {f"{module.__name__}:{name}": getattr(module, name) for module, name in self.globals}

    def _write_globals(self, values):
        for module, name in self.globals:
            key = f"{module.__name__}:{name}"
            if key in values:
                setattr(module, name, values[key])

    # ================= running user code =================

    def error(self, message):
        self.log(message, Status.error, "logStatusError")
        return Status.error

    def run(self, what, fn):
        try:
            with self._forward_logs(), self._in_model_dir():
                fn()
        except Exception as e:
            self._forward_output()
            return self.error(f"{what} failed: {e!r}\n{traceback.format_exc()}")
        self._forward_output()
        return Status.ok

    @contextlib.contextmanager
    def _in_model_dir(self):
        """With [model] cwd: run model code in that folder of the FMU, so relative paths such as
        open("weather.csv") find the files copied with `sources`."""
        if self.cwd is None:
            yield
            return
        previous = os.getcwd()
        os.chdir(self.cwd)
        try:
            yield
        finally:
            os.chdir(previous)

    def _forward_output(self):
        """Send what the model printed (stdout/stderr, also from C code) to the importer's log."""
        if self._output is None:
            return
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()
        self._output.seek(self._position)
        text = self._output.read().decode("utf-8", errors="replace")
        self._position = self._output.tell()
        if text.strip() and self.logging_on:
            self.log(f"[output] {text.rstrip()}", Status.ok, self.info_category)

    @contextlib.contextmanager
    def _forward_logs(self):
        """Forward `logging` records emitted by the user's code to the importer.

        The handler is only installed while user code runs, because UniFMU can only
        carry a log message while it is processing a command.
        """
        handler = _ForwardingHandler(self)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            yield
        finally:
            root.removeHandler(handler)

    def _to_python(self, var, value):
        value = self._to_python_value(var, value)
        converter = self.converters.get(var["name"])
        return converter(value) if converter is not None else value

    def _to_python_value(self, var, value):
        enum = self.enums.get(var.get("declared_type"))
        if var.get("dimensions"):
            if enum is not None:
                value = [list(enum)[x - 1] for x in value]
            value = reshape(value, [int(self.values[d]) if isinstance(d, str) else d for d in var["dimensions"]])
            if var.get("numpy"):
                import numpy
                value = numpy.array(value)
            return value
        if enum is not None:
            return list(enum)[value - 1]
        return value

    def _from_python(self, var, value):
        if var.get("dimensions"):
            flat = flatten(value.tolist() if hasattr(value, "tolist") else value)
            n = self.size(var)
            if len(flat) != n:
                raise ValueError(f"{var['name']} has {len(flat)} values, expected {n}")
            return [self._scalar_from_python(var, x) for x in flat]
        return self._scalar_from_python(var, value)

    def _scalar_from_python(self, var, value):
        if var["type"] == "Enumeration":
            enum = self.enums.get(var.get("declared_type"))
            if enum is not None and isinstance(value, enum):
                return list(enum).index(value) + 1
        if value is None:
            raise TypeError(f"{var['name']} is None")
        return coerce(var["type"], plain_number(value, var.get("unit")))

    def _run_setup(self, after_construction):
        """[model] setup: "module:function" calls run before construction, method names after it."""
        for step in self.interface.get("setup", []):
            is_method = ":" not in step["call"]
            if is_method != after_construction:
                continue
            target = get_path(self.obj, step["call"]) if is_method else resolve_reference(step["call"])
            target(*[resolve_constant(a) for a in step.get("args", [])],
                   **{k: resolve_constant(v) for k, v in step.get("kwargs", {}).items()})

    def _positional(self, clock=None):
        """Values of variables bound to positional arguments (to = "pos:N"), in order."""
        bound = sorted(
            (int(v["to"]["name"]), self._to_python(v, self.values[v["name"]]))
            for v in self.variables
            if v.get("to", {}).get("kind") == "pos" and _clock_of(v) == clock
        )
        return [value for _, value in bound]

    def _bound_target(self, kind, clock):
        """The function whose arguments `kind` ("init" or "arg") variables are bound to."""
        if kind == "init":
            create = self.interface["entry"].get("create")
            return getattr(self.entry, create) if create else self.entry
        return self._target(clock)

    def _bound(self, kind, clock=None):
        """{python name: value} of every variable bound to a constructor/call argument.

        Variables bound to items (to = "arg:pair[0]", "arg:params[key]") are put together into
        a tuple or dict argument.
        """
        bound = {
            v["to"]["name"]: self._to_python(v, self.values[v["name"]])
            for v in self.variables
            if v.get("to", {}).get("kind") == kind and _clock_of(v) == clock
        }
        objects = any("." in name and "[" not in name for name in bound)
        return assemble_items(bound, self._bound_target(kind, clock) if objects else None)

    def _apply_attributes(self, clock=None):
        """Write variables bound to attributes (to = "attr:...") or setter methods (to = "call:...")
        onto the model object."""
        for v in self.variables:
            kind = v.get("to", {}).get("kind")
            if kind in ("attr", "call") and _clock_of(v) == clock:
                value = self._to_python(v, self.values[v["name"]])
                if kind == "attr":
                    set_path(self.obj, v["to"]["name"], value)
                else:
                    get_path(self.obj, v["to"]["name"])(value)

    def _call(self, time, step_size, clock=None):
        if clock is None:
            kwargs = dict(self.call_constants if self.is_class else self.constants)
            kwargs.update(self._bound("arg"))
        else:
            kwargs = self._bound("arg", clock=clock)
        sources = {"time": time, "step_size": step_size, "end_time": time + step_size}
        epochs = self.interface.get("time_epochs", {})
        for arg, source in self.interface.get("time_args", {}).items():
            if clock is None or arg in self.clocks[clock].get("time_args", ()):
                kwargs[arg] = sources[source]
                if arg in epochs:   # a date-time: the epoch plus the FMU time in seconds
                    kwargs[arg] = datetime.datetime.fromisoformat(epochs[arg]) + datetime.timedelta(seconds=kwargs[arg])
        self._apply_attributes(clock=clock)
        return self._target(clock)(*self._positional(clock), **kwargs)

    def _target(self, clock):
        if clock is None:
            return getattr(self.obj, self.interface["entry"]["call"]) if self.is_class else self.entry
        call = self.clocks[clock]["call"]
        if ":" in call:
            return resolve_reference(call)
        return getattr(self.obj, call) if self.is_class else getattr(self.module, call)

    def _source_value(self, source, result, have_result, missing_ok=False):
        """Return (found, value) for a {"kind": "return"|"attr", "name": ...} source."""
        try:
            if source["kind"] == "return":
                if not have_result:
                    return False, None
                return True, pick(result, source.get("name"))
            return True, get_path(self.obj, source["name"])
        except (AttributeError, KeyError, IndexError):
            if missing_ok:
                return False, None
            raise

    def _read_results(self, result, have_result, update_states, missing_ok, clock=None):
        for v in self.variables:
            if "from" not in v or _clock_of(v) != clock:
                continue
            try:
                found, value = self._source_value(v["from"], result, have_result)
            except (AttributeError, KeyError, IndexError) as e:
                if missing_ok:
                    continue
                raise LookupError(f"{v['name']}: cannot read {describe(v['from'])} ({e!r})") from e
            if found and value is None and missing_ok:
                continue  # e.g. an attribute the model only sets after its first step
            if found:
                self.values[v["name"]] = self._from_python(v, value)
        if update_states:
            for v in self.variables:
                if "next" in v:
                    try:
                        _, value = self._source_value(v["next"], result, True)
                    except (AttributeError, KeyError, IndexError) as e:
                        raise LookupError(f"state {v['name']}: cannot read {describe(v['next'])} ({e!r})") from e
                    self.values[v["name"]] = self._from_python(v, value)

    def _refresh_calculated_parameters(self):
        for v in self.variables:
            if v["causality"] == "calculatedParameter" and v["from"]["kind"] == "attr":
                self.values[v["name"]] = self._from_python(v, get_path(self.obj, v["from"]["name"]))


def make_engine(resources_dir, log, info_category="logAll"):
    """The engine for an FMU: one model, or several connected ones ([composite])."""
    interface = json.loads((Path(resources_dir) / "interface.json").read_text())
    if interface.get("composite"):
        return CompositeEngine(resources_dir, log, info_category)
    return Engine(resources_dir, log, info_category)


class CompositeEngine:
    """Several models (parts), each run by its own Engine from resources/parts/<name>/, stepped in
    order. Before a part runs, its inputs connected to other parts' outputs get their current
    values. The FMU's variables are the parts' unconnected ones, named <part>.<variable>."""

    def __init__(self, resources_dir, log, info_category="logAll"):
        self.resources_dir = Path(resources_dir)
        self.log = log
        self.interface = json.loads((self.resources_dir / "interface.json").read_text())
        hf_cache = self.resources_dir / "hf_cache"
        if hf_cache.is_dir():   # Hugging Face models bundled by fmugen build, shared by the parts
            os.environ.update(HF_HUB_CACHE=str(hf_cache), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        self.parts = {p["name"]: Engine(self.resources_dir / p["dir"], log, info_category)
                      for p in self.interface["parts"]}
        self.variables = self.interface["variables"]
        self.by_reference = {v["valueReference"]: v for v in self.variables}
        self.elements = {} if self.interface.get("fmi_version") != 2 else {
            v["valueReference"] + k: (v, k) for v in self.variables if v.get("dimensions")
            for k in range(math.prod(v["dimensions"]))}
        self.connections = [(tuple(c["from"]), tuple(c["to"])) for c in self.interface["connections"]]
        self.clocks, self.clock_active = {}, {}
        self.time = self.interface.get("experiment", {}).get("start_time", 0.0)

    # ---- helpers ----

    @property
    def logging_on(self):
        return all(e.logging_on for e in self.parts.values())

    @logging_on.setter
    def logging_on(self, on):
        for engine in self.parts.values():
            engine.logging_on = on

    @property
    def terminate_requested(self):
        return any(e.terminate_requested for e in self.parts.values())

    def _all(self, method, *args):
        return max((getattr(e, method)(*args) for e in self.parts.values()), default=Status.ok)

    def _feed(self, name):
        """Copy the connected outputs into the inputs of part `name`."""
        for (src, src_ref), (dst, dst_ref) in self.connections:
            if dst != name:
                continue
            status, values = self.parts[src].get_values([src_ref])
            if status == Status.ok:
                status = self.parts[dst].set_values([dst_ref], values)
            if status != Status.ok:
                return status
        return Status.ok

    def _target(self, r):
        """(part engine, its value reference, element or None) for one of the FMU's references."""
        if r in self.elements:
            var, k = self.elements[r]
            return self.parts[var["part"]], var["local"], k
        var = self.by_reference.get(r)
        if var is None or "part" not in var:
            return None, None, None
        return self.parts[var["part"]], var["local"], None

    def error(self, message):
        self.log(message, Status.error, "logStatusError")
        return Status.error

    # ---- life cycle ----

    def reset(self):
        self.time = self.interface.get("experiment", {}).get("start_time", 0.0)
        return self._all("reset")

    def setup_experiment(self, start_time, stop_time=None, tolerance=None):
        self.time = start_time
        return self._all("setup_experiment", start_time, stop_time, tolerance)

    def enter_initialization_mode(self):
        return self._all("enter_initialization_mode")

    def exit_initialization_mode(self, next_mode="step"):
        status = Status.ok
        for name, engine in self.parts.items():
            status = max(status, self._feed(name))
            if status < Status.error:
                status = max(status, engine.exit_initialization_mode(next_mode))
            if status >= Status.error:
                return status
        return status

    def do_step(self, current_time, step_size):
        status, ticked = Status.ok, False
        for name, engine in self.parts.items():
            status = max(status, self._feed(name))
            if status < Status.error:
                part_status, part_ticked = engine.do_step(current_time, step_size)
                status, ticked = max(status, part_status), ticked or part_ticked
            if status >= Status.error:
                return status, ticked
        self.time = current_time + step_size
        return status, ticked

    def terminate(self):
        return self._all("terminate")

    def enter_configuration_mode(self):
        return self.error("a composite FMU has no structural parameters")

    def exit_configuration_mode(self):
        return self.error("a composite FMU has no structural parameters")

    def enter_event_mode(self):
        return self._all("enter_event_mode")

    def enter_step_mode(self):
        return self._all("enter_step_mode")

    def update_discrete_states(self):
        results = [e.update_discrete_states() for e in self.parts.values()]
        times = [t for _, _, t in results if t is not None]
        return max(s for s, _, _ in results), any(t for _, t, _ in results), (min(times) if times else None)

    # ---- values ----

    def size(self, var):
        return math.prod(var["dimensions"]) if var.get("dimensions") else None

    def get_values(self, references):
        values = []
        for r in references:
            var = self.by_reference.get(r)
            if var is not None and var["causality"] == "independent":
                values.append(self.time)
                continue
            engine, local, element = self._target(r)
            if engine is None:
                return self.error(f"unknown value reference {r}"), []
            status, part_values = engine.get_values([local if element is None else local + element])
            if status != Status.ok:
                return status, []
            values.extend(part_values)
        return Status.ok, values

    def set_values(self, references, values):
        values, cursor = list(values), 0
        for r in references:
            engine, local, element = self._target(r)
            if engine is None:
                return self.error(f"unknown value reference {r}")
            n = 1 if element is not None else (self.size(self.by_reference[r]) or 1)
            status = engine.set_values([local if element is None else local + element], values[cursor:cursor + n])
            cursor += n
            if status != Status.ok:
                return status
        return Status.ok

    # ---- clocks: a composite FMU has none, so every reference is unknown ----

    def _first(self):
        return next(iter(self.parts.values()))

    def set_clocks(self, references, values):
        return self._first().set_clocks(references, values)

    def get_clocks(self, references):
        return self._first().get_clocks(references)

    def get_intervals(self, references):
        return self._first().get_intervals(references)

    def set_intervals(self, references, intervals):
        return self._first().set_intervals(references, intervals)

    def get_shifts(self, references):
        return self._first().get_shifts(references)

    def set_shifts(self, references, shifts):
        return self._first().set_shifts(references, shifts)

    # ---- state ----

    def serialize(self):
        states = {}
        for name, engine in self.parts.items():
            status, data = engine.serialize()
            if status != Status.ok:
                return status, b""
            states[name] = data
        return Status.ok, b"M" + pickle.dumps({"parts": states, "time": self.time})

    def deserialize(self, data):
        if data[:1] != b"M":
            return self.error("not an FMU state saved by this composite FMU")
        state = pickle.loads(data[1:])
        self.time = state["time"]
        return max((self.parts[name].deserialize(part) for name, part in state["parts"].items()),
                   default=Status.ok)


class _ForwardingHandler(logging.Handler):
    def __init__(self, engine):
        super().__init__(level=logging.DEBUG)
        self.engine = engine

    def emit(self, record):
        if not self.engine.logging_on:
            return
        if record.levelno >= logging.ERROR:
            status, category = Status.error, "logStatusError"
        elif record.levelno >= logging.WARNING:
            status, category = Status.warning, "logStatusWarning"
        else:
            status, category = Status.ok, self.engine.info_category
        message = f"[{record.name}] {record.getMessage()}"
        if record.exc_info:
            message += "\n" + "".join(traceback.format_exception(*record.exc_info))
        self.engine.log(message, status, category)


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
        return get_path(importlib.import_module(module_name), attr)
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
        obj = copy.copy(default)
        for field, value in fields.items():
            setattr(obj, field, value)
        return obj
    if cls is None:
        raise ValueError(f"{name}: no default and no class annotation to build it from {sorted(fields)}")
    return cls(**fields)


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
    """Call 'module:function(args)' and return the result. Arguments are Python literals or
    dotted names of importable objects, e.g. load_from_hub(repo_id="sb3/x", filename="m.zip")."""
    target, args, kwargs = parse_call_text(text)

    def value(node):
        try:
            return ast.literal_eval(node)
        except ValueError:
            return resolve_reference(ast.unparse(node))

    return resolve_reference(target)(*[value(a) for a in args], **{k: value(v) for k, v in kwargs.items()})


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
    """A pint quantity (anything with .magnitude and .units) as a number, in `unit` when given;
    a one-value pandas/xarray column as its value."""
    if type(value).__module__.split(".")[0] in ("pandas", "xarray") and getattr(value, "size", None) == 1:
        value = value.item()
    if hasattr(value, "magnitude") and hasattr(value, "units"):
        return value.m_as(unit) if unit and hasattr(value, "m_as") else value.magnitude
    return value


def get_path(obj, path):
    """Follow a dotted path through attributes, mapping keys and sequence indexes: "state.T", "rewards.speed", "4.x"."""
    for part in path.split("."):
        if isinstance(obj, Mapping) and (part in obj or not hasattr(obj, part)) or _labelled(obj) and part in obj:   # "options.update": the method
            obj = obj[part]
        elif part.isdigit() and isinstance(obj, (tuple, list)):
            obj = obj[int(part)]
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


def fraction(value):
    """float -> (counter, resolution) for FMI 3 *Fraction functions."""
    f = Fraction(str(value))
    return f.numerator, f.denominator
