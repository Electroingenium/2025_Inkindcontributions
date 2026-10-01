import importlib.util
import json
import keyword
from pathlib import Path

FMI_TYPES = ("Real", "Integer", "Boolean", "String")
DEFAULT_START = {"Real": 0.0, "Integer": 0, "Boolean": False, "String": ""}


class InterfaceError(ValueError):
    pass


def load_module(model_path):
    model_path = Path(model_path).resolve()
    spec = importlib.util.spec_from_file_location(model_path.stem, model_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _infer_type(name, info):
    if "type" in info:
        if info["type"] not in FMI_TYPES:
            raise InterfaceError(f"{name}: unknown type {info['type']!r}, expected one of {FMI_TYPES}")
        return info["type"]
    start = info.get("start")
    # bool before int: bool is a subclass of int
    if isinstance(start, bool):
        return "Boolean"
    if isinstance(start, int):
        return "Integer"
    if isinstance(start, str):
        return "String"
    return "Real"


def _variables(declared, causality):
    if not isinstance(declared, dict):
        raise InterfaceError(f"{causality} declaration must be a dict, got {type(declared).__name__}")
    variables = []
    for name, info in declared.items():
        info = info or {}
        if not name.isidentifier() or keyword.iskeyword(name):
            raise InterfaceError(f"{name!r} is not a valid Python identifier")
        fmi_type = _infer_type(name, info)
        var = {
            "name": name,
            "causality": causality,
            "type": fmi_type,
            "variability": "continuous" if fmi_type == "Real" else "discrete",
        }
        if causality == "parameter":
            var["variability"] = "fixed"
        if causality != "output":
            var["start"] = info.get("start", DEFAULT_START[fmi_type])
        if info.get("unit"):
            var["unit"] = info["unit"]
        if info.get("description"):
            var["description"] = info["description"]
        variables.append(var)
    return variables


def load_interface(model_path, probe=True):
    """Import the model and return its interface spec (JSON-serialisable dict)."""
    model_path = Path(model_path).resolve()
    module = load_module(model_path)

    for attr in ("INPUTS", "OUTPUTS"):
        if not hasattr(module, attr):
            raise InterfaceError(f"{model_path.name} does not define {attr}")
    if not callable(getattr(module, "step", None)):
        raise InterfaceError(f"{model_path.name} does not define a step(**inputs) function")

    variables = (
        _variables(module.INPUTS, "input")
        + _variables(getattr(module, "PARAMETERS", {}), "parameter")
        + _variables(module.OUTPUTS, "output")
    )

    names = [v["name"] for v in variables]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise InterfaceError(f"duplicate variable names: {sorted(duplicates)}")

    for vr, var in enumerate(variables):
        var["valueReference"] = vr

    if probe:
        args = {v["name"]: v["start"] for v in variables if v["causality"] != "output"}
        result = module.step(**args)
        if not isinstance(result, dict):
            raise InterfaceError(f"step() must return a dict, got {type(result).__name__}")
        expected = {v["name"] for v in variables if v["causality"] == "output"}
        missing = expected - result.keys()
        if missing:
            raise InterfaceError(f"step() result is missing outputs: {sorted(missing)}")

    return {
        "model_module": model_path.stem,
        "model_doc": (module.__doc__ or "").strip(),
        "variables": variables,
    }


def write_interface(interface, path):
    Path(path).write_text(json.dumps(interface, indent=2))
