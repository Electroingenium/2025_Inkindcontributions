"""fmugen.toml: loading, validation and normalisation into the interface spec.

The config describes how an unmodified Python model maps onto an FMU: which callable
to use, which of its arguments and attributes are FMU variables, and FMU-level
settings such as the default experiment. See docs/config.md for the full reference.

`load_config()` only reads and validates the file. `normalize()` needs the imported
entry object (to tell a function from a class and to check argument names) and
returns the interface spec that is written to resources/interface.json and read by
the runtime engine (templates/fmugen_runtime.py) and the XML writer (description.py).
The spec has the same shape for FMI 2 and FMI 3, except for the type names and the
FMI 3-only parts (arrays, structural parameters, clocks, events).
"""
import datetime
import inspect
import keyword
import tomllib
from pathlib import Path, PurePosixPath

FMI_VERSIONS = (2, 3)
FLOAT_TYPES = ("Real", "Float32", "Float64")
INT_TYPES = ("Integer", "Int8", "UInt8", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64")
FMI_TYPES = (*FLOAT_TYPES, *INT_TYPES, "Boolean", "String", "Binary", "Enumeration")
# Config type name -> type name in the spec, per FMI version (missing: not available)
TYPE_NAMES = {
    2: {"Real": "Real", "Float64": "Real", "Integer": "Integer", "Int32": "Integer",
        "Boolean": "Boolean", "String": "String", "Enumeration": "Enumeration"},
    3: {"Real": "Float64", "Integer": "Int32", **{t: t for t in FMI_TYPES if t not in ("Real", "Integer")}},
}
DEFAULT_START = {
    **{t: 0.0 for t in FLOAT_TYPES}, **{t: 0 for t in INT_TYPES},
    "Boolean": False, "String": "", "Binary": "", "Enumeration": 1,
}

MODEL_DIR = "fmugen_model"   # the user's code, inside the FMU's resources/ folder

# Module names already used by the UniFMU backend and fmugen in resources/
RESERVED_MODULES = {"model", "backend", "main", "abstract_backend", "schemas", "fmugen_runtime", "fmugen_launch"}

# Config section -> FMI causality, in valueReference order
SECTIONS = {
    "structural_parameters": "structuralParameter",
    "parameters": "parameter",
    "calculated_parameters": "calculatedParameter",
    "inputs": "input",
    "states": "local",
    "outputs": "output",
    "locals": "local",
}

MODEL_KEYS = {
    "entry", "call", "name", "description", "author", "sources", "requirements",
    "constants", "call_constants", "init_call", "terminate", "fmi_version", "setup", "kind", "create",
    "save_state", "cwd", "globals",
}
EXPERIMENT_KEYS = {"start_time", "stop_time", "step_size", "tolerance", "fixed_step"}
TIME_SOURCES = ("time", "step_size", "end_time")
COMMON_VAR_KEYS = {
    "type", "start", "unit", "description", "variability", "initial",
    "min", "max", "nominal", "quantity", "items", "enum", "dimensions", "numpy", "convert",
}
VAR_KEYS = {
    "structural_parameters": COMMON_VAR_KEYS | {"to", "attr"},
    "parameters": COMMON_VAR_KEYS | {"to", "attr"},
    "calculated_parameters": COMMON_VAR_KEYS | {"from"},
    "inputs": COMMON_VAR_KEYS | {"to", "clocks"},
    "states": COMMON_VAR_KEYS | {"to", "next"},
    "outputs": COMMON_VAR_KEYS | {"from", "depends_on", "clocks"},
    "locals": COMMON_VAR_KEYS | {"from", "clocks"},
}
CLOCK_KEYS = {"causality", "interval_variability", "interval", "shift", "interval_from", "call", "from", "description"}
INTERVAL_VARIABILITIES = ("constant", "fixed", "tunable", "changing", "countdown", "triggered")
EVENT_KEYS = {"terminate", "next_event_time"}
TOP_KEYS = {"model", "experiment", "time", "clocks", "events", *SECTIONS}
FMI3_ONLY = "requires FMI 3 ([model] fmi_version = 3 or fmugen build --fmi 3)"

VARIABILITIES = {
    "structuralParameter": ("fixed", "tunable"),
    "parameter": ("fixed", "tunable"),
    "calculatedParameter": ("fixed", "tunable"),
    "input": ("discrete", "continuous"),
    "output": ("constant", "discrete", "continuous"),
    "local": ("constant", "discrete", "continuous"),
}
INITIALS = {
    "structuralParameter": ("exact",),
    "parameter": ("exact",),
    "calculatedParameter": ("approx", "calculated"),
    "input": (),
    "output": ("exact", "calculated"),
    "local": ("exact", "approx", "calculated"),
}


class InterfaceError(ValueError):
    pass


class Config:
    """A validated fmugen.toml (or an equivalent dict produced by inference)."""

    def __init__(self, data, base_dir):
        self.data = data
        self.base_dir = Path(base_dir).resolve()
        _check_keys(data, TOP_KEYS, "fmugen.toml")
        self.model = data.get("model", {})
        _check_keys(self.model, MODEL_KEYS, "[model]")
        if "entry" not in self.model:
            raise InterfaceError("[model] entry is required, e.g. entry = \"model.py:simulate\"")
        if self.model.get("fmi_version", 2) not in FMI_VERSIONS:
            raise InterfaceError(f"[model] fmi_version must be one of {FMI_VERSIONS}")
        self.experiment = data.get("experiment", {})
        _check_keys(self.experiment, EXPERIMENT_KEYS, "[experiment]")
        for section, keys in VAR_KEYS.items():
            for name, info in data.get(section, {}).items():
                if not isinstance(info, dict):
                    raise InterfaceError(f"[{section}] {name} must be a table, e.g. {name} = {{ start = 0.0 }}")
                _check_keys(info, keys, f"[{section}] {name}")
        for name, info in data.get("clocks", {}).items():
            _check_keys(info, CLOCK_KEYS, f"[clocks.{name}]")
        _check_keys(data.get("events", {}), EVENT_KEYS, "[events]")

        self.entry_target, self.entry_name = parse_entry(self.model["entry"])
        self.entry_is_file = self.entry_target.endswith(".py")
        self.requirements = list(self.model.get("requirements", []))
        if "cwd" in self.model:
            cwd = self._inside(str(self.model["cwd"]), "cwd")
            if not cwd.is_dir():
                raise InterfaceError(f"[model] cwd {self.model['cwd']!r} is not a folder (relative to {self.base_dir})")

    def fmi_version(self, override=None):
        return override or self.model.get("fmi_version", 2)

    # ---- files ----

    def entry_file(self):
        return self._inside(self.entry_target, "entry") if self.entry_is_file else None

    def model_cwd(self):
        """Where model code runs, relative to the FMU's resources/ folder ([model] cwd), or None."""
        if "cwd" not in self.model:
            return None
        rel = self._inside(str(self.model["cwd"]), "cwd").relative_to(self.base_dir).as_posix()
        return (PurePosixPath(MODEL_DIR) / rel).as_posix()

    def source_files(self):
        """[(absolute source path, path relative to the config dir)] to copy into the FMU."""
        paths = [self.entry_target] if self.entry_is_file else []
        paths += self.model.get("sources", [])
        files = []
        for rel in paths:
            src = self._inside(rel, "sources")
            if not src.exists():
                raise InterfaceError(f"{rel} does not exist (relative to {self.base_dir})")
            files.append((src, PurePosixPath(src.relative_to(self.base_dir).as_posix())))
        return files

    def _inside(self, rel, what):
        path = (self.base_dir / rel).resolve()
        if not path.is_relative_to(self.base_dir):
            raise InterfaceError(f"{what} {rel!r} must be inside {self.base_dir}")
        return path

    def entry_import(self):
        """(module name, sys.path entries relative to resources/) used to import the entry."""
        sys_path = []
        if not self.entry_is_file:
            module = self.entry_target
        else:
            rel = PurePosixPath(self.entry_file().relative_to(self.base_dir).as_posix())
            dirs = rel.parts[:-1]
            # Import as a package module when the file sits in a package (supports relative
            # imports); the file's own directory is also on sys.path for flat imports.
            root = len(dirs)
            while root > 0 and (self.base_dir.joinpath(*dirs[:root]) / "__init__.py").exists():
                root -= 1
            module = ".".join(dirs[root:] + (rel.stem,))
            for path in (PurePosixPath(MODEL_DIR, *dirs), PurePosixPath(MODEL_DIR, *dirs[:root])):
                if str(path) not in sys_path:
                    sys_path.append(str(path))
        if module.split(".")[0] in RESERVED_MODULES:
            raise InterfaceError(
                f"model module {module!r} clashes with a UniFMU backend module "
                f"({', '.join(sorted(RESERVED_MODULES))}); rename the file"
            )
        return module, sys_path


def load_config(path):
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise InterfaceError(f"{path}: {e}") from e
    return Config(data, path.parent)


def parse_entry(entry):
    target, sep, name = entry.rpartition(":")
    if not sep or not target or not name.isidentifier():
        raise InterfaceError(
            f"entry {entry!r} must look like 'path/to/file.py:Name' or 'package.module:Name'"
        )
    return target, name


def parse_binding(text, kinds, what):
    kind, _, name = text.partition(":")
    if kind not in kinds:
        raise InterfaceError(f"{what}: {text!r} must start with one of {', '.join(k + ':' for k in kinds)}")
    if kind != "return" and not name:
        raise InterfaceError(f"{what}: {text!r} needs a name after '{kind}:'")
    return {"kind": kind, "name": name or None}


def normalize(config, entry_obj, module_name, sys_path, model_name=None, author=None, fmi_version=None):
    """Return the interface spec for a validated Config and its imported entry object."""
    model = config.model
    version = config.fmi_version(fmi_version)
    if version not in FMI_VERSIONS:
        raise InterfaceError(f"unknown FMI version {version!r}, expected one of {FMI_VERSIONS}")
    notes = []
    if model.get("kind", "auto") not in ("auto", "function"):
        raise InterfaceError('[model] kind must be "function" (call a class like a function on every step)')
    # kind = "function": a class whose constructor does the work is called like a function on every step
    is_class = inspect.isclass(entry_obj) and model.get("kind") != "function"
    if not is_class and not callable(entry_obj):
        raise InterfaceError(f"{config.model['entry']} is neither a function nor a class")
    # A function entry with a call method is a factory: called once with the parameters, like a
    # constructor; `call` runs on what it returns (e.g. silero_vad:load_silero_vad, call = "__call__").
    factory = not inspect.isclass(entry_obj) and isinstance(model.get("call"), str)
    if factory and model.get("kind") == "function":
        raise InterfaceError('[model] kind = "function" and call exclude each other for a function entry')
    is_class = is_class or factory
    kind = "class" if is_class else "function"
    create = model.get("create")   # a classmethod that builds the object, e.g. "from_pretrained"
    if create is not None:
        if not is_class or factory:
            raise InterfaceError("[model] create only applies to classes")
        if not isinstance(create, str) or not callable(getattr(entry_obj, create, None)):
            raise InterfaceError(f"[model] create: {entry_obj.__name__} has no classmethod {create!r}")
        constructor = getattr(entry_obj, create)
    elif factory:
        constructor = entry_obj
    else:
        constructor = entry_obj.__init__ if is_class else None

    call = model.get("call")
    step_call = call is not False   # call = false: nothing runs on doStep, only clocks run code
    if not step_call and not config.data.get("clocks"):
        raise InterfaceError("[model] call = false needs [clocks] (otherwise the model never runs)")
    if is_class and not step_call:
        call = None
        init_sig = _signature(constructor)
        call_sig = None
    elif factory:
        init_sig = _signature(constructor)
        call_sig = None   # the method belongs to the object the factory returns, known only at runtime
    elif is_class:
        if call is None:
            if not any("__call__" in vars(k) for k in entry_obj.__mro__[:-1]):
                raise InterfaceError(f"{entry_obj.__name__} is a class: set [model] call to the method run on each step")
            call = "__call__"
        if not callable(getattr(entry_obj, call, None)):
            raise InterfaceError(f"{entry_obj.__name__} has no method {call!r}")
        init_sig = _signature(constructor)
        call_sig = _signature(getattr(entry_obj, call))
    else:
        for key in ("call", "terminate", "call_constants"):
            if key in model and not (key == "call" and call is False):
                raise InterfaceError(f"[model] {key} only applies to classes; {model['entry']} is a function")
        init_sig = None
        call_sig = _signature(entry_obj) if step_call else None

    def check_arg(sig, arg, what):
        if sig is not None and not _accepts(sig, arg):
            raise InterfaceError(f"{what}: {arg!r} is not an argument of {sig[1]}")

    constants = model.get("constants", {})
    call_constants = model.get("call_constants", {})
    for name in constants:
        check_arg(init_sig if is_class else call_sig, name, f"[model] constants.{name}")
    for name in call_constants:
        check_arg(call_sig, name, f"[model] call_constants.{name}")
    for table, values in (("constants", constants), ("call_constants", call_constants)):
        for name, value in values.items():
            if isinstance(value, dict) and "call" in value:   # computed when the FMU initializes
                from fmugen.templates.fmugen_runtime import parse_call_text
                try:
                    parse_call_text(str(value["call"]))
                except (ValueError, SyntaxError) as e:
                    raise InterfaceError(f"[model] {table}.{name}: {e}") from e

    time_args, time_epochs = {}, {}
    for arg, source in config.data.get("time", {}).items():
        if isinstance(source, dict):   # { source = "time", epoch = "2026-06-21T00:00:00+00:00" }: a datetime
            unknown = set(source) - {"source", "epoch"}
            if unknown:
                raise InterfaceError(f"[time] {arg}: unknown keys {sorted(unknown)}")
            if "epoch" in source:
                try:
                    datetime.datetime.fromisoformat(str(source["epoch"]))
                except ValueError as e:
                    raise InterfaceError(f"[time] {arg}: epoch {source['epoch']!r} is not an ISO 8601 date-time") from e
                time_epochs[arg] = str(source["epoch"])
            source = source.get("source", "time")
        if source not in TIME_SOURCES:
            raise InterfaceError(f"[time] {arg} = {source!r}: expected one of {TIME_SOURCES}")
        if arg in time_epochs and source == "step_size":
            raise InterfaceError(f"[time] {arg}: epoch applies to \"time\" and \"end_time\", not \"step_size\"")
        check_arg(call_sig, arg, f"[time] {arg}")
        time_args[arg] = source

    clock_names = set(config.data.get("clocks", {}))
    structural = set(config.data.get("structural_parameters", {}))
    if version == 2:
        for key in ("structural_parameters", "clocks"):
            if config.data.get(key):
                raise InterfaceError(f"[{key}] {FMI3_ONLY}")
        if config.data.get("events"):
            notes.append("[events] is ignored for FMI 2: an FMI 2 FMU cannot signal events or ask to stop")

    clocks = [_clock(name, info, entry_obj, is_class, time_args)
              for name, info in config.data.get("clocks", {}).items()]
    clock_sigs = {c["name"]: c.pop("_signature") for c in clocks}

    variables, type_definitions = [], {}
    for section, causality in SECTIONS.items():
        for name, info in config.data.get(section, {}).items():
            var = _variable(section, causality, name, info, is_class, type_definitions,
                            version, structural, clock_names)
            to = var.get("to")
            if to and to["kind"] in ("init", "arg"):
                clock = (var.get("clocks") or [None])[0]
                sig = init_sig if to["kind"] == "init" else (clock_sigs[clock] if clock else call_sig)
                from fmugen.templates.fmugen_runtime import split_item
                check_arg(sig, split_item(to["name"])[0], f"[{section}] {name}")
            variables.append(var)

    if not variables:
        raise InterfaceError(
            "the config defines no FMU variables: add [inputs]/[parameters] and [outputs] "
            "(the model's arguments and results could not be inferred)"
        )
    for clock_name in [None, *clock_names]:
        positions = sorted(int(v["to"]["name"]) for v in variables
                           if v.get("to", {}).get("kind") == "pos" and (v.get("clocks") or [None])[0] == clock_name)
        if positions != list(range(len(positions))):
            raise InterfaceError(f"positional arguments (to = \"pos:N\") must be numbered 0, 1, 2, ... without gaps; "
                                 f"got {positions}")

    names = [v["name"] for v in variables]
    duplicates = sorted({n for n in names if names.count(n) > 1} | (set(names) & clock_names))
    if duplicates:
        raise InterfaceError(f"duplicate variable or clock names: {duplicates}")
    for clock in clocks:
        clocked_inputs = [v["name"] for v in variables if v.get("clocks") == [clock["name"]] and "to" in v]
        if clocked_inputs and clock["causality"] == "input" and not clock.get("call"):
            raise InterfaceError(f"[clocks.{clock['name']}] has clocked inputs {clocked_inputs} but no call")
    if version == 3:
        if "time" in names:
            raise InterfaceError("FMI 3 reserves the variable name 'time' for the independent variable; rename it")
        variables.append({"name": "time", "causality": "independent", "variability": "continuous",
                          "type": "Float64", "description": "Simulation time"})
    vr = 0
    for var in variables:
        var["valueReference"] = vr
        vr += element_count(var) if version == 2 else 1   # FMI 2: an array takes one reference per element
    for vr, clock in enumerate(clocks, start=vr):
        clock["valueReference"] = vr

    inputs = {v["name"] for v in variables if v["causality"] == "input"}
    for var in variables:
        for dep in var.get("depends_on", []):
            if dep not in inputs:
                raise InterfaceError(f"[outputs] {var['name']}: depends_on {dep!r} is not an input")

    events = {}
    if version == 3:
        kinds = ("return", "attr") if is_class else ("return",)
        for key, text in config.data.get("events", {}).items():
            events[key] = parse_binding(text, kinds, f"[events] {key}")

    experiment = dict(config.experiment)
    if experiment.get("fixed_step") and "step_size" not in experiment:
        raise InterfaceError("[experiment] fixed_step = true requires step_size")

    doc = inspect.getdoc(entry_obj) or inspect.getdoc(inspect.getmodule(entry_obj)) or ""
    return {
        "spec_version": 1,
        "fmi_version": version,
        "model_name": model_name or model.get("name") or config.entry_name,
        "description": model.get("description", doc.strip().splitlines()[0] if doc.strip() else ""),
        "author": author if author is not None else model.get("author", ""),
        "entry": {
            "module": module_name,
            "name": config.entry_name,
            "kind": kind,
            "create": create,
            "factory": factory,
            "call": call if is_class and step_call else None,
            "step": step_call,
            "init_call": model.get("init_call", not is_class and step_call),
            "terminate": model.get("terminate"),
        },
        "sys_path": sys_path,
        "cwd": config.model_cwd(),
        "globals": _globals(model.get("globals", [])),
        "setup": _setup(model.get("setup", []), is_class),
        "constants": constants,
        "call_constants": call_constants,
        "time_args": time_args,
        "time_epochs": time_epochs,
        "experiment": experiment,
        "type_definitions": type_definitions,
        "variables": variables,
        "clocks": clocks,
        "events": events,
        "has_event_mode": bool(clocks or events),
        "can_get_and_set_state": _save_state(model) is not False,
        "save_state": _save_state(model),
        "notes": notes,
    }


def _save_state(model):
    """[model] save_state: how the FMU saves and restores its state.

    true: the whole model object (pickle, else cloudpickle); false: not supported; a list of
    attribute paths: only those attributes. fmugen init picks one by trying to pickle the object.
    """
    value = model.get("save_state", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, list) and value and all(
            isinstance(p, str) and all(part.isidentifier() for part in p.split(".")) for p in value):
        return list(value)
    raise InterfaceError('[model] save_state must be true, false, or a list of attribute names like ["_state"]')


def parse_call(text):
    """'module:function(arg, ..., key=arg, ...)' or 'method(...)' -> {call, args, kwargs}.

    Arguments are Python literals or dotted references to importable objects
    (e.g. psychrolib.SI); references are resolved when the FMU initializes.
    """
    import ast

    def argument(node):
        try:
            value = ast.literal_eval(node)
            return value if isinstance(value, (bool, int, float, str)) else {"python": ast.unparse(node)}
        except ValueError:
            if not isinstance(node, (ast.Attribute, ast.Name)):
                raise InterfaceError(f"[model] setup {text!r}: arguments must be literals or names")
            return {"ref": ast.unparse(node)}

    call, paren, rest = text.partition("(")
    args, kwargs = [], {}
    if paren:
        if not rest.endswith(")"):
            raise InterfaceError(f"[model] setup {text!r}: missing ')'")
        try:
            parsed = ast.parse(f"_({rest}", mode="eval").body
        except SyntaxError as e:
            raise InterfaceError(f"[model] setup {text!r}: {e.msg}") from e
        args = [argument(node) for node in parsed.args]
        for keyword in parsed.keywords:
            if keyword.arg is None:
                raise InterfaceError(f"[model] setup {text!r}: **kwargs is not supported")
            kwargs[keyword.arg] = argument(keyword.value)
    return {"call": call.strip(), "args": args, "kwargs": kwargs}


def _setup(steps, is_class):
    """[model] setup: calls run when the FMU initializes, before the model is used."""
    if isinstance(steps, (str, dict)):
        steps = [steps]
    normalized = []
    for step in steps:
        if isinstance(step, str):
            step = parse_call(step)
        if not isinstance(step, dict) or "call" not in step:
            raise InterfaceError("[model] setup entries are \"module:function\", \"method\", "
                                 "or { call = ..., args = [...], kwargs = {...} }")
        _check_keys(step, {"call", "args", "kwargs"}, "[model] setup")
        if ":" not in step["call"] and not is_class:
            raise InterfaceError(f"[model] setup {step['call']!r}: use \"module:function\" (the model is a function)")
        normalized.append({"call": step["call"], "args": list(step.get("args", [])),
                           "kwargs": dict(step.get("kwargs", {}))})
    return normalized


def _clock(name, info, entry_obj, is_class, time_args):
    where = f"[clocks.{name}]"
    if not name.isidentifier() or keyword.iskeyword(name):
        raise InterfaceError(f"{where}: clock names must be valid Python identifiers")
    causality = info.get("causality", "input")
    if causality not in ("input", "output"):
        raise InterfaceError(f"{where}: causality must be \"input\" or \"output\"")
    variability = info.get("interval_variability", "constant" if "interval" in info else "triggered")
    if variability not in INTERVAL_VARIABILITIES:
        raise InterfaceError(f"{where}: interval_variability must be one of {INTERVAL_VARIABILITIES}")
    clock = {"name": name, "causality": causality, "interval_variability": variability, "_signature": None}
    if info.get("description"):
        clock["description"] = str(info["description"])
    kinds = ("return", "attr") if is_class else ("return",)

    if causality == "output":
        if variability != "triggered":
            raise InterfaceError(f"{where}: output clocks are ticked by the model, so they must be \"triggered\"")
        if "from" not in info:
            raise InterfaceError(f"{where}: output clocks need from = \"...\" (a value that is true when it ticks)")
        for key in ("call", "interval", "shift", "interval_from"):
            if key in info:
                raise InterfaceError(f"{where}: {key} only applies to input clocks")
        clock["from"] = parse_binding(info["from"], kinds, where)
        return clock

    if "from" in info:
        raise InterfaceError(f"{where}: from only applies to output clocks")
    if variability in ("constant", "fixed", "tunable"):
        if "interval" not in info:
            raise InterfaceError(f"{where}: a {variability} clock needs interval = <seconds>")
        clock["interval"] = float(info["interval"])
        clock["shift"] = float(info.get("shift", 0.0))
    elif "interval" in info or "shift" in info:
        raise InterfaceError(f"{where}: interval and shift only apply to constant, fixed and tunable clocks")
    if variability in ("changing", "countdown"):
        if "interval_from" not in info:
            raise InterfaceError(f"{where}: a {variability} clock needs interval_from = \"...\" (the next interval)")
        clock["interval_from"] = parse_binding(info["interval_from"], kinds, where)
    elif "interval_from" in info:
        raise InterfaceError(f"{where}: interval_from only applies to changing and countdown clocks")

    if info.get("call"):
        call = info["call"]
        if ":" in call:
            from fmugen.templates.fmugen_runtime import resolve_reference
            try:
                target = resolve_reference(call)
            except Exception as e:
                raise InterfaceError(f"{where}: cannot import {call!r}: {e!r}") from e
        elif is_class:
            target = getattr(entry_obj, call, None)
        else:
            target = getattr(inspect.getmodule(entry_obj), call, None)
        if not callable(target):
            raise InterfaceError(f"{where}: call {call!r} is not a method or function of the model")
        clock["call"] = call
        clock["_signature"] = signature = _signature(target)
        clock["time_args"] = [arg for arg in time_args if signature is None or _accepts(signature, arg)]
    return clock


def _globals(refs):
    """[model] globals = ["package.module:NAME", ...]: module-level state of the model."""
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise InterfaceError('[model] globals must be a list like ["package.module:NAME"]')
    from fmugen.templates.fmugen_runtime import split_global
    for ref in refs:
        module, sep, name = ref.partition(":")
        if not sep or not module or not name.isidentifier():
            raise InterfaceError(f"[model] globals: {ref!r} must look like 'package.module:NAME'")
        try:
            split_global(ref)
        except Exception as e:
            raise InterfaceError(f"[model] globals: cannot find {ref!r}: {e!r}") from e
    return list(refs)


def element_count(var):
    """Number of elements of a fixed-size array variable (1 for a scalar)."""
    n = 1
    for d in var.get("dimensions", ()):
        n *= d
    return n


def _variable(section, causality, name, info, is_class, type_definitions, version=2, structural=(), clocks=()):
    where = f"[{section}] {name}"
    parts = name.split(".") if section in ("outputs", "locals") else [name]   # outputs may be "zone.T"
    if not all(p.isidentifier() and not keyword.iskeyword(p) for p in parts):
        raise InterfaceError(f"{where}: variable names must be valid Python identifiers"
                             + (" or dotted ones (zone.T)" if section in ("outputs", "locals") else ""))

    config_type = _type(where, info, section)
    fmi_type = TYPE_NAMES[version].get(config_type)
    if fmi_type is None:
        raise InterfaceError(f"{where}: type {config_type} {FMI3_ONLY}")
    var = {"name": name, "causality": causality, "type": fmi_type}
    is_float = fmi_type in FLOAT_TYPES

    if "dimensions" in info:   # FMI 2 has no arrays: one scalar variable per element, x[1], x[2], ...
        dims = info["dimensions"]
        if section == "structural_parameters":
            raise InterfaceError(f"{where}: structural parameters are scalars")
        if not isinstance(dims, list) or not dims:
            raise InterfaceError(f"{where}: dimensions must be a list like [3] or [\"n\", 2]")
        for d in dims:
            if isinstance(d, str):
                if d not in structural:
                    raise InterfaceError(f"{where}: dimension {d!r} is not a structural parameter")
            elif not isinstance(d, int) or isinstance(d, bool) or d < 1:
                raise InterfaceError(f"{where}: dimension {d!r} must be a positive integer or a structural parameter")
        var["dimensions"] = list(dims)
        if info.get("numpy"):
            var["numpy"] = True
    elif "numpy" in info:
        raise InterfaceError(f"{where}: numpy only applies to arrays (set dimensions)")
    if "convert" in info:
        # a function applied to the value before the model gets it, e.g. "torch:tensor"
        if section not in ("structural_parameters", "parameters", "inputs", "states"):
            raise InterfaceError(f"{where}: convert only applies to values passed to the model")
        from fmugen.templates.fmugen_runtime import (
            resolve_reference,  # same resolution as at runtime
        )
        if info["convert"] == "pint":   # a pint quantity in the variable's unit
            if not info.get("unit"):
                raise InterfaceError(f"{where}: convert = \"pint\" needs a unit")
            reference = "pint:get_application_registry"
        else:
            reference = str(info["convert"])
        try:
            converter = resolve_reference(reference)
        except Exception as e:
            raise InterfaceError(f"{where}: cannot import convert {info['convert']!r}: {e!r}") from e
        if not callable(converter):
            raise InterfaceError(f"{where}: convert {info['convert']!r} is not callable")
        var["convert"] = str(info["convert"])

    if "clocks" in info:
        if version == 2:
            raise InterfaceError(f"{where}: clocked variables {FMI3_ONLY}")
        names = [info["clocks"]] if isinstance(info["clocks"], str) else list(info["clocks"])
        if len(names) != 1 or names[0] not in clocks:
            raise InterfaceError(f"{where}: clocks must name exactly one clock from [clocks]")
        var["clocks"] = names

    if fmi_type == "Enumeration":
        type_name, items = _enumeration(where, name, info)
        type_definitions[type_name] = {"items": items, "enum": info.get("enum")}
        var["declared_type"] = type_name
        if isinstance(info.get("start"), str):
            if info["start"] not in items:
                raise InterfaceError(f"{where}: start {info['start']!r} is not one of {items}")
            info = {**info, "start": items.index(info["start"]) + 1}

    # variability
    default_variability = {
        "parameter": "fixed", "calculatedParameter": "fixed", "structuralParameter": "fixed",
    }.get(causality, "continuous" if is_float and "clocks" not in var else "discrete")
    variability = info.get("variability", default_variability)
    if variability not in VARIABILITIES[causality]:
        raise InterfaceError(f"{where}: variability must be one of {VARIABILITIES[causality]}")
    if variability == "continuous" and not is_float:
        raise InterfaceError(f"{where}: only floating-point variables can be continuous")
    var["variability"] = variability

    # start / initial
    has_start = "start" in info
    if section in ("structural_parameters", "parameters", "inputs", "states"):
        initial = "exact" if section != "inputs" else None
        var["start"] = info.get("start", DEFAULT_START[fmi_type])
    elif section == "outputs":
        initial = "exact" if has_start else "calculated"
    else:
        initial = "approx" if has_start else "calculated"
    initial = info.get("initial", initial)
    if section == "states" and initial != "exact":
        raise InterfaceError(f"{where}: states always have initial = \"exact\"")
    if initial is not None and initial not in INITIALS[causality]:
        raise InterfaceError(f"{where}: initial must be one of {INITIALS[causality]}")
    if initial == "calculated" and has_start:
        raise InterfaceError(f"{where}: a start value requires initial = \"exact\" or \"approx\"")
    if initial in ("exact", "approx"):
        var["start"] = info.get("start", DEFAULT_START[fmi_type])
    if initial is not None:
        var["initial"] = initial
    if "start" in var:
        start = var["start"]
        if isinstance(start, list):
            if "dimensions" not in var:
                raise InterfaceError(f"{where}: a list start needs dimensions")
            var["start"] = [_check_value(where, fmi_type, x) for x in start]
        else:
            var["start"] = _check_value(where, fmi_type, start)

    for key in ("unit", "description", "quantity"):
        if info.get(key):
            var[key] = str(info[key])
    for key in ("min", "max", "nominal"):
        if key in info:
            if fmi_type not in (*FLOAT_TYPES, *INT_TYPES, "Enumeration") or (key == "nominal" and not is_float):
                raise InterfaceError(f"{where}: {key} is not allowed for {fmi_type} variables")
            var[key] = info[key]

    # bindings to the user's code
    if section in ("structural_parameters", "parameters", "inputs", "states"):
        default = "init" if (section in ("parameters", "structural_parameters") and is_class) else "arg"
        kinds = ("init", "arg", "pos", "attr", "call") if is_class else ("arg", "pos")
        var["to"] = parse_binding(info.get("to", f"{default}:{name}"), kinds, where)
        if var["to"]["kind"] == "pos" and not var["to"]["name"].isdigit():
            raise InterfaceError(f"{where}: pos needs an argument index, e.g. to = \"pos:0\"")
        if "clocks" in var and var["to"]["kind"] == "init":
            raise InterfaceError(f"{where}: a clocked input is passed to its clock's call, not the constructor")
        if section == "states":
            if "next" not in info:
                raise InterfaceError(f"{where}: states need next = \"...\" (where the next value comes from)")
            var["next"] = parse_binding(info["next"], ("return", "attr") if is_class else ("return",), where)
    else:
        default = f"attr:{name}" if is_class else f"return:{name}"
        var["from"] = parse_binding(info.get("from", default), ("return", "attr") if is_class else ("return",), where)
        if section == "calculated_parameters" and var["from"]["kind"] != "attr":
            raise InterfaceError(f"{where}: calculated parameters are read from an attribute (from = \"attr:...\")")

    if section in ("parameters", "structural_parameters"):
        attr = info.get("attr")
        if attr is not None and not is_class:
            raise InterfaceError(f"{where}: attr only applies to classes")
        if variability == "tunable" and is_class:
            if var["to"]["kind"] == "attr" or var["to"]["kind"] == "init" and attr is None:
                attr = var["to"]["name"]
            if attr:
                var["attr"] = attr

    if section == "outputs" and "depends_on" in info:
        var["depends_on"] = list(info["depends_on"])
    return var


def _type(where, info, section=None):
    if "type" in info:
        if info["type"] not in FMI_TYPES:
            raise InterfaceError(f"{where}: unknown type {info['type']!r}, expected one of {FMI_TYPES}")
        return info["type"]
    if "items" in info or "enum" in info:
        return "Enumeration"
    if section == "structural_parameters":
        return "UInt64"
    start = info.get("start")
    if isinstance(start, list) and start:
        start = start[0]
    # bool before int: bool is a subclass of int
    if isinstance(start, bool):
        return "Boolean"
    if isinstance(start, int):
        return "Integer"
    if isinstance(start, str):
        return "String"
    return "Real"


def _enumeration(where, name, info):
    if "enum" in info:
        from fmugen.templates.fmugen_runtime import (
            resolve_reference,  # same resolution as at runtime
        )
        try:
            enum = resolve_reference(info["enum"])
        except Exception as e:
            raise InterfaceError(f"{where}: cannot import enum {info['enum']!r}: {e!r}") from e
        return enum.__name__, [member.name for member in enum]
    if not info.get("items"):
        raise InterfaceError(f"{where}: Enumeration variables need items = [...] or enum = \"module:Class\"")
    return f"{name}_type", [str(item) for item in info["items"]]


def _check_value(where, fmi_type, value):
    from fmugen.templates.fmugen_runtime import coerce
    if fmi_type in FLOAT_TYPES:
        expected = (int, float)
    else:
        expected = {"Boolean": (bool,), "String": (str,), "Binary": (str,)}.get(fmi_type, (int,))
    if isinstance(value, bool) and fmi_type != "Boolean" or not isinstance(value, expected):
        raise InterfaceError(f"{where}: start {value!r} is not a valid {fmi_type}")
    try:
        coerce(fmi_type, value)  # integer ranges, hex for Binary
    except ValueError as e:
        raise InterfaceError(f"{where}: start {value!r}: {e}") from e
    return float(value) if fmi_type in FLOAT_TYPES else value


def _signature(fn):
    try:
        return inspect.signature(fn), getattr(fn, "__qualname__", repr(fn))
    except (TypeError, ValueError):
        return None


def _accepts(sig, arg):
    signature, _ = sig
    params = signature.parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    p = params.get(arg)
    return p is not None and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


def _check_keys(table, allowed, where):
    if not isinstance(table, dict):
        raise InterfaceError(f"{where} must be a table")
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise InterfaceError(f"{where}: unknown key(s) {unknown}; allowed: {sorted(allowed)}")
