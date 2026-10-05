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
import importlib
import json
import logging
import math
import pickle
import sys
import traceback
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
        self.variables = self.interface["variables"]
        self.by_name = {v["name"]: v for v in self.variables}
        self.by_reference = {v["valueReference"]: v for v in self.variables}
        self.clocks = {c["name"]: c for c in self.interface.get("clocks", [])}
        self.clock_by_reference = {c["valueReference"]: c for c in self.clocks.values()}
        self.events = self.interface.get("events", {})
        self.experiment = self.interface.get("experiment", {})

        self.logging_on = True
        self.module, self.entry = load_entry(self.interface, self.resources_dir)
        entry = self.interface["entry"]
        self.is_class = entry["kind"] == "class"
        self.enums = {
            name: resolve_reference(td["enum"])
            for name, td in self.interface.get("type_definitions", {}).items() if td.get("enum")
        }
        self.constants = {k: resolve_constant(v) for k, v in self.interface.get("constants", {}).items()}
        self.call_constants = {k: resolve_constant(v) for k, v in self.interface.get("call_constants", {}).items()}
        self.reset()

    # ================= life cycle =================

    def reset(self):
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
                self.obj = self.entry(**kwargs)
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
        for r in references:
            var = self.by_reference.get(r)
            if var is None:
                return self.error(f"unknown value reference {r}")
            n = self.size(var)
            if len(values) < (n or 1):
                return self.error(f"not enough values for {var['name']}")
            raw = [values.pop(0) for _ in range(n)] if n is not None else values.pop(0)
            problem = self._settable(var)
            if problem:
                return self.error(f"{var['name']} ({var['causality']}) cannot be set {problem}")
            try:
                value = [coerce(var["type"], x) for x in raw] if n is not None else coerce(var["type"], raw)
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
        state = {
            "values": self.values, "obj": self.obj, "time": self.time, "mode": self.mode,
            "clock_active": self.clock_active, "clock_interval": self.clock_interval,
            "clock_shift": self.clock_shift, "terminate_requested": self.terminate_requested,
            "clock_last_tick": self.clock_last_tick,
        }
        try:
            return Status.ok, pickle.dumps(state)
        except Exception as e:
            self.log(f"cannot serialize FMU state: {e!r}", Status.error, "logStatusError")
            return Status.error, b""

    def deserialize(self, data):
        try:
            state = pickle.loads(data)
        except Exception as e:
            return self.error(f"cannot deserialize FMU state: {e!r}")
        self.values = dict(state["values"])
        self.obj, self.time, self.mode = state["obj"], state["time"], state["mode"]
        self.clock_active = dict(state.get("clock_active", self.clock_active))
        self.clock_interval = dict(state.get("clock_interval", self.clock_interval))
        self.clock_shift = dict(state.get("clock_shift", self.clock_shift))
        self.terminate_requested = state.get("terminate_requested", False)
        self.clock_last_tick = dict(state.get("clock_last_tick", {}))
        return Status.ok

    # ================= running user code =================

    def error(self, message):
        self.log(message, Status.error, "logStatusError")
        return Status.error

    def run(self, what, fn):
        try:
            with self._forward_logs():
                fn()
        except Exception as e:
            return self.error(f"{what} failed: {e!r}\n{traceback.format_exc()}")
        return Status.ok

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
        return coerce(var["type"], value)

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

    def _bound(self, kind, clock=None):
        """{python name: value} of every variable bound to a constructor/call argument."""
        return {
            v["to"]["name"]: self._to_python(v, self.values[v["name"]])
            for v in self.variables
            if v.get("to", {}).get("kind") == kind and _clock_of(v) == clock
        }

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
        for arg, source in self.interface.get("time_args", {}).items():
            if clock is None or arg in self.clocks[clock].get("time_args", ()):
                kwargs[arg] = sources[source]
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


def resolve_constant(value):
    if isinstance(value, dict) and len(value) == 1:
        if "python" in value:
            return ast.literal_eval(value["python"])
        if "ref" in value:
            return resolve_reference(value["ref"])
    return value


def get_path(obj, path):
    for part in path.split("."):
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
    if isinstance(result, Mapping):
        return result[key]
    if key.isdigit() and isinstance(result, (tuple, list)):
        return result[int(key)]
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
        return bool(value)
    if fmi_type == "Binary":
        if isinstance(value, str):
            return bytes.fromhex(value)
        return bytes(value)
    return str(value)


def fraction(value):
    """float -> (counter, resolution) for FMI 3 *Fraction functions."""
    f = Fraction(str(value))
    return f.numerator, f.denominator
