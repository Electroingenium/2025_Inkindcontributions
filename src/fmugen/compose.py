"""Composite FMUs: several fmugen models in one FMU, connected output to input.

A composite fmugen.toml lists other fmugen configs (the parts) and connections:

    [composite]
    name = "pv_system"
    parts = { sky = "irradiance/fmugen.toml", cell = "cell/fmugen.toml" }   # run in this order
    connections = ["sky.poa_global -> cell.poa_global"]

Each part is built as usual into resources/parts/<name>/ and run by its own runtime Engine
(templates/fmugen_runtime.py, CompositeEngine). This module validates the composite config and
combines the parts' interfaces into the FMU's interface.
"""
import keyword
import tomllib
from pathlib import Path

from fmugen.config import FMI_VERSIONS, InterfaceError, element_count, load_config

COMPOSITE_KEYS = {"name", "description", "author", "parts", "connections", "fmi_version"}
TOP_KEYS = {"composite", "experiment"}
PARTS_DIR = "parts"


class Composite:
    def __init__(self, path):
        self.path = Path(path)
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        unknown = set(data) - TOP_KEYS
        if unknown:
            raise InterfaceError(f"{self.path}: a composite config has only [composite] and [experiment], "
                                 f"not {sorted(unknown)}")
        table = data["composite"]
        unknown = set(table) - COMPOSITE_KEYS
        if unknown:
            raise InterfaceError(f"[composite]: unknown keys {sorted(unknown)}")
        self.data = table
        self.experiment = dict(data.get("experiment", {}))
        self.fmi_version = table.get("fmi_version", 2)
        if self.fmi_version not in FMI_VERSIONS:
            raise InterfaceError(f"[composite] fmi_version must be one of {FMI_VERSIONS}")
        parts = table.get("parts")
        if not isinstance(parts, dict) or len(parts) < 2:
            raise InterfaceError('[composite] parts must name two or more configs: { a = "a/fmugen.toml", ... }')
        self.parts = {}
        for name, rel in parts.items():
            if not name.isidentifier() or keyword.iskeyword(name):
                raise InterfaceError(f"[composite] parts: {name!r} must be a Python identifier")
            part_path = (self.path.parent / rel).resolve()
            if part_path.is_dir():
                part_path = part_path / "fmugen.toml"
            if not part_path.is_file():
                raise InterfaceError(f"[composite] parts.{name}: {rel!r} is not a fmugen.toml")
            config = load_config(part_path)
            for key in ("clocks", "structural_parameters", "events"):
                if config.data.get(key):
                    raise InterfaceError(f"[composite] parts.{name}: [{key}] is not supported inside a composite FMU")
            self.parts[name] = config
        self.connections = [_connection(text) for text in table.get("connections", [])]
        entries = [c.entry_target for c in self.parts.values() if c.entry_is_file]
        stems = [Path(e).stem for e in entries]
        clashes = sorted({s for s in stems if stems.count(s) > 1})
        if clashes:
            raise InterfaceError(f"[composite] parts share the module name(s) {clashes}: all parts run in one "
                                 "Python process, so rename one of the files")


def is_composite(target):
    path = Path(target)
    if path.is_dir():
        path = path / "fmugen.toml"
    if path.suffix != ".toml" or not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise InterfaceError(f"{path}: {e}") from e
    return path if "composite" in data else None


def _connection(text):
    source, arrow, target = (str(text)).partition("->")
    ends = []
    for end in (source.strip(), target.strip()):
        part, dot, variable = end.partition(".")
        if not arrow or not dot or not part or not variable:
            raise InterfaceError(f"[composite] connection {text!r} must look like 'part.output -> part.input'")
        ends.append((part, variable))
    return tuple(ends)


def combine(composite, interfaces, version, model_name=None, author=None):
    """The FMU's interface: the parts' variables not fed by a connection, named <part>.<name>."""
    by_name = {name: {v["name"]: v for v in interface["variables"]} for name, interface in interfaces.items()}
    connections, fed = [], set()
    for (src, src_var), (dst, dst_var) in composite.connections:
        for part, var in ((src, src_var), (dst, dst_var)):
            if part not in by_name:
                raise InterfaceError(f"[composite] connection: there is no part {part!r}")
            if var not in by_name[part]:
                raise InterfaceError(f"[composite] connection: part {part!r} has no variable {var!r}")
        source, target = by_name[src][src_var], by_name[dst][dst_var]
        if target["causality"] != "input":
            raise InterfaceError(f"[composite] connection: {dst}.{dst_var} is not an input")
        if source["causality"] in ("input", "independent"):
            raise InterfaceError(f"[composite] connection: {src}.{src_var} is an input, not a result")
        if (dst, dst_var) in fed:
            raise InterfaceError(f"[composite] connection: {dst}.{dst_var} is fed twice")
        if element_count(source) != element_count(target):
            raise InterfaceError(f"[composite] connection: {src}.{src_var} and {dst}.{dst_var} have different sizes")
        fed.add((dst, dst_var))
        connections.append({"from": [src, source["valueReference"]], "to": [dst, target["valueReference"]]})

    variables, type_definitions = [], {}
    for part, interface in interfaces.items():
        for td_name, definition in interface.get("type_definitions", {}).items():
            type_definitions[f"{part}.{td_name}"] = definition
        for var in interface["variables"]:
            if var["causality"] == "independent" or (part, var["name"]) in fed:
                continue
            new = dict(var, name=f"{part}.{var['name']}", part=part, local=var["valueReference"])
            if var.get("declared_type"):
                new["declared_type"] = f"{part}.{var['declared_type']}"
            if "depends_on" in var:
                new["depends_on"] = [f"{part}.{d}" for d in var["depends_on"] if (part, d) not in fed]
            variables.append(new)
    if version == 3:
        variables.append({"name": "time", "causality": "independent", "variability": "continuous",
                          "type": "Float64", "description": "Simulation time"})
    vr = 0
    for var in variables:
        var["valueReference"] = vr
        vr += element_count(var) if version == 2 else 1

    experiment = dict(composite.experiment)
    fixed = {i.get("experiment", {}).get("step_size") for i in interfaces.values()
             if i.get("experiment", {}).get("fixed_step")}
    if len(fixed) > 1:
        raise InterfaceError(f"[composite] parts need different fixed step sizes: {sorted(fixed)}")
    if fixed and "step_size" not in experiment:
        experiment.update(step_size=fixed.pop(), fixed_step=True)
    return {
        "spec_version": 1,
        "composite": True,
        "fmi_version": version,
        "model_name": model_name or composite.data.get("name") or composite.path.parent.name,
        "description": composite.data.get("description", "fmugen composite of " + ", ".join(interfaces)),
        "author": author if author is not None else composite.data.get("author", ""),
        "parts": [{"name": part, "dir": f"{PARTS_DIR}/{part}"} for part in interfaces],
        "connections": connections,
        "variables": variables,
        "type_definitions": type_definitions,
        "experiment": experiment,
        "clocks": [],
        "events": {},
        "has_event_mode": False,
        "can_get_and_set_state": all(i.get("can_get_and_set_state", True) for i in interfaces.values()),
        "capture_output": any(i.get("capture_output") for i in interfaces.values()),
    }
