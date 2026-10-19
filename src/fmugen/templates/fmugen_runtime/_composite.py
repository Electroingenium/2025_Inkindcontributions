"""CompositeEngine: several models stepped in order, and the factory that picks the right engine."""
import json
import math
import os
import pickle
from pathlib import Path

from fmugen.templates.fmugen_runtime._constants import SPEC_VERSION, Status
from fmugen.templates.fmugen_runtime._engine import Engine


def make_engine(resources_dir, log, info_category="logAll"):
    """The engine for an FMU: one model, or several connected ones ([composite])."""
    interface = json.loads((Path(resources_dir) / "interface.json").read_text())
    check_spec_version(interface)
    if interface.get("composite"):
        return CompositeEngine(resources_dir, log, info_category)
    return Engine(resources_dir, log, info_category)


def check_spec_version(interface):
    """Refuse an interface.json written for another runtime (a part or file from another fmugen version)."""
    found = interface.get("spec_version")
    if found != SPEC_VERSION:
        raise RuntimeError(f"interface.json has spec_version {found!r}, but this fmugen runtime reads version "
                           f"{SPEC_VERSION}: rebuild the FMU with one fmugen version")


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
        for p in self.interface["parts"]:
            check_spec_version(json.loads((self.resources_dir / p["dir"] / "interface.json").read_text()))
        self.parts = {p["name"]: Engine(self.resources_dir / p["dir"], log, info_category)
                      for p in self.interface["parts"]}
        self.variables = self.interface["variables"]
        self.by_reference = {v["valueReference"]: v for v in self.variables}
        self.elements = {} if self.interface.get("fmi_version") != 2 else {
            v["valueReference"] + k: (v, k) for v in self.variables if v.get("dimensions")
            for k in range(math.prod(v["dimensions"]))}
        self.connections = [(tuple(c["from"]), tuple(c["to"])) for c in self.interface["connections"]]
        # the parts' clocks, <part>.<clock>: each reference is passed on to its part
        self.clocks = {c["name"]: c for c in self.interface.get("clocks", [])}
        self.clock_by_reference = {c["valueReference"]: c for c in self.clocks.values()}
        self.time = self.interface.get("experiment", {}).get("start_time", 0.0)

    # ---- helpers ----

    @property
    def logging_on(self):
        return all(e.logging_on for e in self.parts.values())

    @logging_on.setter
    def logging_on(self, on):
        for engine in self.parts.values():
            engine.logging_on = on

    def set_debug_logging(self, logging_on, categories=()):
        return self._all("set_debug_logging", logging_on, categories)

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
        # a part that discards its step undoes the whole step: the parts before it are put back too
        saved = None
        if any(e.discard_on for e in self.parts.values()) and self.interface.get("can_get_and_set_state", True):
            saved = self.serialize()[1]
        status, ticked = Status.ok, False
        for name, engine in self.parts.items():
            status = max(status, self._feed(name))
            if status < Status.error:
                part_status, part_ticked = engine.do_step(current_time, step_size)
                status, ticked = max(status, part_status), ticked or part_ticked
            if status == Status.discard:
                if saved:
                    self.deserialize(saved)
                return status, False
            if status >= Status.error:
                return status, ticked
        self.time = current_time + step_size
        return status, ticked

    def terminate(self):
        return self._all("terminate")

    def _configurable(self):
        """The parts with structural parameters (only they have a configuration mode)."""
        return [e for e in self.parts.values() if any(v["causality"] == "structuralParameter" for v in e.variables)]

    def enter_configuration_mode(self):
        parts = self._configurable()
        if not parts:
            return self.error("this FMU has no structural parameters")
        return max(e.enter_configuration_mode() for e in parts)

    def exit_configuration_mode(self):
        parts = self._configurable()
        if not parts:
            return self.error("this FMU has no structural parameters")
        return max(e.exit_configuration_mode() for e in parts)

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
        if not var.get("dimensions"):
            return None
        engine, local, _ = self._target(var["valueReference"])
        return engine.size(engine.by_reference[local])   # its part knows the structural parameters

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

    # ---- clocks: each one belongs to a part ----

    def _clock(self, r):
        """(part engine, the clock's reference in that part) for one of the FMU's clock references."""
        clock = self.clock_by_reference.get(r)
        return (self.parts[clock["part"]], clock["local"]) if clock else (None, None)

    def _clock_values(self, method, references, columns=1):
        """Call a part's get method (returning status and `columns` lists) for each clock reference."""
        lists = [[] for _ in range(columns)]
        for r in references:
            engine, local = self._clock(r)
            if engine is None:
                return (self.error(f"value reference {r} is not a clock"), *([] for _ in lists))
            status, *values = getattr(engine, method)([local])
            if status != Status.ok:
                return (status, *([] for _ in lists))
            for target, part_values in zip(lists, values):
                target.extend(part_values)
        return (Status.ok, *lists)

    def _clock_set(self, method, references, values):
        for r, value in zip(references, values):
            engine, local = self._clock(r)
            if engine is None:
                return self.error(f"value reference {r} is not a clock")
            status = getattr(engine, method)([local], [value])
            if status != Status.ok:
                return status
        return Status.ok

    @property
    def clock_active(self):
        return {name: self.parts[c["part"]].clock_active[c["name"].partition(".")[2]]
                for name, c in self.clocks.items()}

    def drop_output_ticks(self):
        return self._all("drop_output_ticks")

    def set_clocks(self, references, values):
        return self._clock_set("set_clocks", references, values)

    def get_clocks(self, references):
        return self._clock_values("get_clocks", references)

    def get_intervals(self, references):
        return self._clock_values("get_intervals", references, columns=2)

    def set_intervals(self, references, intervals):
        return self._clock_set("set_intervals", references, intervals)

    def get_shifts(self, references):
        return self._clock_values("get_shifts", references)

    def set_shifts(self, references, shifts):
        return self._clock_set("set_shifts", references, shifts)

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
