"""fmugen.toml: loading, validation and normalisation into the interface spec.

The config describes how an unmodified Python model maps onto an FMU: which callable
to use, which of its arguments and attributes are FMU variables, and FMU-level
settings such as the default experiment. See docs/config.md for the full reference.

`load_config()` only reads and validates the file. `normalize()` needs the imported
entry object (to tell a function from a class and to check argument names) and
returns the interface spec that is written to resources/interface.json and read by
the runtime adapter (templates/model.py) and the XML writer (description.py).
"""
import inspect
import keyword
import tomllib
from pathlib import Path, PurePosixPath

FMI_TYPES = ("Real", "Integer", "Boolean", "String", "Enumeration")
DEFAULT_START = {"Real": 0.0, "Integer": 0, "Boolean": False, "String": "", "Enumeration": 1}

# Directories inside the FMU's resources/ folder
MODEL_DIR = "fmugen_model"   # the user's code
SITE_DIR = "site"            # vendored requirements

# Module names already used by the UniFMU backend in resources/
RESERVED_MODULES = {"model", "backend", "main", "abstract_backend", "schemas"}

# Config section -> FMI causality, in valueReference order
SECTIONS = {
    "parameters": "parameter",
    "calculated_parameters": "calculatedParameter",
    "inputs": "input",
    "states": "local",
    "outputs": "output",
    "locals": "local",
}

MODEL_KEYS = {
    "entry", "call", "name", "description", "author", "sources", "requirements",
    "constants", "call_constants", "init_call", "terminate",
}
EXPERIMENT_KEYS = {"start_time", "stop_time", "step_size", "tolerance", "fixed_step"}
TIME_SOURCES = ("time", "step_size", "end_time")
COMMON_VAR_KEYS = {
    "type", "start", "unit", "description", "variability", "initial",
    "min", "max", "nominal", "quantity", "items", "enum",
}
VAR_KEYS = {
    "parameters": COMMON_VAR_KEYS | {"to", "attr"},
    "calculated_parameters": COMMON_VAR_KEYS | {"from"},
    "inputs": COMMON_VAR_KEYS | {"to"},
    "states": COMMON_VAR_KEYS | {"to", "next"},
    "outputs": COMMON_VAR_KEYS | {"from", "depends_on"},
    "locals": COMMON_VAR_KEYS | {"from"},
}
TOP_KEYS = {"model", "experiment", "time", *SECTIONS}

VARIABILITIES = {
    "parameter": ("fixed", "tunable"),
    "calculatedParameter": ("fixed", "tunable"),
    "input": ("discrete", "continuous"),
    "output": ("constant", "discrete", "continuous"),
    "local": ("constant", "discrete", "continuous"),
}
INITIALS = {
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
        self.experiment = data.get("experiment", {})
        _check_keys(self.experiment, EXPERIMENT_KEYS, "[experiment]")
        for section, keys in VAR_KEYS.items():
            for name, info in data.get(section, {}).items():
                if not isinstance(info, dict):
                    raise InterfaceError(f"[{section}] {name} must be a table, e.g. {name} = {{ start = 0.0 }}")
                _check_keys(info, keys, f"[{section}] {name}")

        self.entry_target, self.entry_name = parse_entry(self.model["entry"])
        self.entry_is_file = self.entry_target.endswith(".py")
        self.requirements = list(self.model.get("requirements", []))

    # ---- files ----

    def entry_file(self):
        return self._inside(self.entry_target, "entry") if self.entry_is_file else None

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

    def entry_import(self, vendored=False):
        """(module name, sys.path entries relative to resources/) used to import the entry."""
        sys_path = [SITE_DIR] if vendored else []
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


def normalize(config, entry_obj, module_name, sys_path, model_name=None, author=None):
    """Return the interface spec for a validated Config and its imported entry object."""
    model = config.model
    is_class = inspect.isclass(entry_obj)
    if not is_class and not callable(entry_obj):
        raise InterfaceError(f"{config.model['entry']} is neither a function nor a class")
    kind = "class" if is_class else "function"

    call = model.get("call")
    if is_class:
        if call is None:
            if not any("__call__" in vars(k) for k in entry_obj.__mro__[:-1]):
                raise InterfaceError(f"{entry_obj.__name__} is a class: set [model] call to the method run on each step")
            call = "__call__"
        if not callable(getattr(entry_obj, call, None)):
            raise InterfaceError(f"{entry_obj.__name__} has no method {call!r}")
        init_sig = _signature(entry_obj.__init__)
        call_sig = _signature(getattr(entry_obj, call))
    else:
        for key in ("call", "terminate", "call_constants"):
            if key in model:
                raise InterfaceError(f"[model] {key} only applies to classes; {model['entry']} is a function")
        init_sig = None
        call_sig = _signature(entry_obj)

    def check_arg(sig, arg, what):
        if sig is not None and not _accepts(sig, arg):
            raise InterfaceError(f"{what}: {arg!r} is not an argument of {sig[1]}")

    constants = model.get("constants", {})
    call_constants = model.get("call_constants", {})
    for name in constants:
        check_arg(init_sig if is_class else call_sig, name, f"[model] constants.{name}")
    for name in call_constants:
        check_arg(call_sig, name, f"[model] call_constants.{name}")

    time_args = config.data.get("time", {})
    for arg, source in time_args.items():
        if source not in TIME_SOURCES:
            raise InterfaceError(f"[time] {arg} = {source!r}: expected one of {TIME_SOURCES}")
        check_arg(call_sig, arg, f"[time] {arg}")

    variables, type_definitions = [], {}
    for section, causality in SECTIONS.items():
        for name, info in config.data.get(section, {}).items():
            var = _variable(section, causality, name, info, is_class, type_definitions)
            to = var.get("to")
            if to and to["kind"] in ("init", "arg"):
                check_arg(init_sig if to["kind"] == "init" else call_sig, to["name"], f"[{section}] {name}")
            variables.append(var)

    names = [v["name"] for v in variables]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise InterfaceError(f"duplicate variable names: {duplicates}")
    for vr, var in enumerate(variables):
        var["valueReference"] = vr

    inputs = {v["name"] for v in variables if v["causality"] == "input"}
    for var in variables:
        for dep in var.get("depends_on", []):
            if dep not in inputs:
                raise InterfaceError(f"[outputs] {var['name']}: depends_on {dep!r} is not an input")

    experiment = dict(config.experiment)
    if experiment.get("fixed_step") and "step_size" not in experiment:
        raise InterfaceError("[experiment] fixed_step = true requires step_size")

    doc = inspect.getdoc(entry_obj) or inspect.getdoc(inspect.getmodule(entry_obj)) or ""
    return {
        "spec_version": 1,
        "model_name": model_name or model.get("name") or config.entry_name,
        "description": model.get("description", doc.strip().splitlines()[0] if doc.strip() else ""),
        "author": author if author is not None else model.get("author", ""),
        "entry": {
            "module": module_name,
            "name": config.entry_name,
            "kind": kind,
            "call": call if is_class else None,
            "init_call": model.get("init_call", not is_class),
            "terminate": model.get("terminate"),
        },
        "sys_path": sys_path,
        "constants": constants,
        "call_constants": call_constants,
        "time_args": time_args,
        "experiment": experiment,
        "type_definitions": type_definitions,
        "variables": variables,
        "can_get_and_set_state": True,
    }


def _variable(section, causality, name, info, is_class, type_definitions):
    where = f"[{section}] {name}"
    if not name.isidentifier() or keyword.iskeyword(name):
        raise InterfaceError(f"{where}: variable names must be valid Python identifiers")

    fmi_type = _type(where, info)
    var = {"name": name, "causality": causality, "type": fmi_type}

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
        "parameter": "fixed", "calculatedParameter": "fixed",
    }.get(causality, "continuous" if fmi_type == "Real" else "discrete")
    variability = info.get("variability", default_variability)
    if variability not in VARIABILITIES[causality]:
        raise InterfaceError(f"{where}: variability must be one of {VARIABILITIES[causality]}")
    if variability == "continuous" and fmi_type != "Real":
        raise InterfaceError(f"{where}: only Real variables can be continuous")
    var["variability"] = variability

    # start / initial
    has_start = "start" in info
    if section in ("parameters", "inputs", "states"):
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
        var["start"] = _check_value(where, fmi_type, var["start"])

    for key in ("unit", "description", "quantity"):
        if info.get(key):
            var[key] = str(info[key])
    for key in ("min", "max", "nominal"):
        if key in info:
            if fmi_type not in ("Real", "Integer", "Enumeration") or (key == "nominal" and fmi_type != "Real"):
                raise InterfaceError(f"{where}: {key} is not allowed for {fmi_type} variables")
            var[key] = info[key]

    # bindings to the user's code
    if section in ("parameters", "inputs", "states"):
        default = "init" if (section == "parameters" and is_class) else "arg"
        kinds = ("init", "arg", "attr") if is_class else ("arg",)
        var["to"] = parse_binding(info.get("to", f"{default}:{name}"), kinds, where)
        if section == "states":
            if "next" not in info:
                raise InterfaceError(f"{where}: states need next = \"...\" (where the next value comes from)")
            var["next"] = parse_binding(info["next"], ("return", "attr") if is_class else ("return",), where)
    else:
        default = f"attr:{name}" if is_class else f"return:{name}"
        var["from"] = parse_binding(info.get("from", default), ("return", "attr") if is_class else ("return",), where)
        if section == "calculated_parameters" and var["from"]["kind"] != "attr":
            raise InterfaceError(f"{where}: calculated parameters are read from an attribute (from = \"attr:...\")")

    if section == "parameters":
        attr = info.get("attr")
        if attr is not None and not is_class:
            raise InterfaceError(f"{where}: attr only applies to classes")
        if variability == "tunable" and is_class:
            if var["to"]["kind"] == "attr":
                attr = var["to"]["name"]
            elif var["to"]["kind"] == "init" and attr is None:
                attr = var["to"]["name"]
            if attr:
                var["attr"] = attr

    if section == "outputs" and "depends_on" in info:
        var["depends_on"] = list(info["depends_on"])
    return var


def _type(where, info):
    if "type" in info:
        if info["type"] not in FMI_TYPES:
            raise InterfaceError(f"{where}: unknown type {info['type']!r}, expected one of {FMI_TYPES}")
        return info["type"]
    if "items" in info or "enum" in info:
        return "Enumeration"
    start = info.get("start")
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
        from fmugen.templates.model import resolve_reference  # same resolution as at runtime
        try:
            enum = resolve_reference(info["enum"])
        except Exception as e:
            raise InterfaceError(f"{where}: cannot import enum {info['enum']!r}: {e!r}") from e
        return enum.__name__, [member.name for member in enum]
    if not info.get("items"):
        raise InterfaceError(f"{where}: Enumeration variables need items = [...] or enum = \"module:Class\"")
    return f"{name}_type", [str(item) for item in info["items"]]


def _check_value(where, fmi_type, value):
    expected = {"Real": (int, float), "Integer": (int,), "Enumeration": (int,), "Boolean": (bool,), "String": (str,)}
    if isinstance(value, bool) and fmi_type != "Boolean" or not isinstance(value, expected[fmi_type]):
        raise InterfaceError(f"{where}: start {value!r} is not a valid {fmi_type}")
    return float(value) if fmi_type == "Real" else value


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
