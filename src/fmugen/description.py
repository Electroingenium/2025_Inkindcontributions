"""modelDescription.xml (FMI 2.0 or 3.0 Co-Simulation) from a fmugen interface spec."""
import itertools
import math
import hashlib
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

LOG_CATEGORIES = [
    ("logStatusWarning", None),
    ("logStatusDiscard", None),
    ("logStatusError", None),
    ("logStatusFatal", None),
    ("logStatusPending", None),
    ("logAll", None),
    ("logUnifmuMessages",
     "Messages related to internal UniFMU functionality. "
     "Enabling this category is required for distributed UniFMUs."),
]

# Replaced after the FMU's files are written by a token derived from their content (stamp_guid),
# so an unchanged model rebuilds to the same GUID / instantiationToken.
GUID_PLACEHOLDER = "{00000000-0000-0000-0000-000000000000}"
GUID_NAMESPACE = uuid.UUID("6f3c1d52-8a4e-4b7a-9d0e-2f5c8b1a7e43")

FLOAT_TYPES = ("Real", "Float32", "Float64")

EXPERIMENT_ATTRIBUTES = {
    "start_time": "startTime", "stop_time": "stopTime",
    "tolerance": "tolerance", "step_size": "stepSize",
}


def build_time():
    """The build time: SOURCE_DATE_EPOCH when set (reproducible builds), else now."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    return datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)


def _format_value(fmi_type, value):
    if fmi_type == "Boolean":
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "INF" if value > 0 else "-INF"
        return repr(value)
    return str(value)


def build_model_description(interface, model_name=None, author=None):
    """Return the modelDescription.xml ElementTree for a fmugen interface spec."""
    variables = interface["variables"]
    experiment = interface.get("experiment", {})
    can_state = "true" if interface.get("can_get_and_set_state", True) else "false"

    root = ET.Element("fmiModelDescription", {
        "fmiVersion": "2.0",
        "modelName": model_name or interface["model_name"],
        "guid": GUID_PLACEHOLDER,
        "description": interface.get("description", ""),
        "author": interface.get("author", "") if author is None else author,
        "generationTool": "fmugen + unifmu",
        "generationDateAndTime": build_time().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variableNamingConvention": "structured" if any(v.get("dimensions") for v in variables) else "flat",
    })

    ET.SubElement(root, "CoSimulation", {
        "modelIdentifier": "unifmu",
        "needsExecutionTool": "true",
        "canNotUseMemoryManagementFunctions": "true",
        "canHandleVariableCommunicationStepSize": "false" if experiment.get("fixed_step") else "true",
        "canGetAndSetFMUstate": can_state,
        "canSerializeFMUstate": can_state,
    })

    units = sorted({v["unit"] for v in variables if v.get("unit") and v["type"] == "Real"})
    if units:
        unit_defs = ET.SubElement(root, "UnitDefinitions")
        for unit in units:
            ET.SubElement(unit_defs, "Unit", {"name": unit})

    type_definitions = interface.get("type_definitions", {})
    if type_definitions:
        type_defs = ET.SubElement(root, "TypeDefinitions")
        for name, definition in type_definitions.items():
            simple_type = ET.SubElement(type_defs, "SimpleType", {"name": name})
            enumeration = ET.SubElement(simple_type, "Enumeration")
            for value, item in enumerate(definition["items"], start=1):
                ET.SubElement(enumeration, "Item", {"name": item, "value": str(value)})

    log_categories = ET.SubElement(root, "LogCategories")
    for name, description in LOG_CATEGORIES:
        attrs = {"name": name}
        if description:
            attrs["description"] = description
        ET.SubElement(log_categories, "Category", attrs)

    experiment_attrs = {
        xml_name: _format_value("Real", float(experiment[key]))
        for key, xml_name in EXPERIMENT_ATTRIBUTES.items() if key in experiment
    }
    if experiment_attrs:
        ET.SubElement(root, "DefaultExperiment", experiment_attrs)

    model_variables = ET.SubElement(root, "ModelVariables")
    index_of = {}   # name -> indexes of its ScalarVariables (several for an array)
    index = 0
    for var, element, name in _scalars(variables):
        index += 1
        index_of.setdefault(var["name"], []).append(index)
        attrs = {
            "name": name,
            "valueReference": str(var["valueReference"] + element),
            "causality": var["causality"],
            "variability": var["variability"],
        }
        if var.get("description"):
            attrs["description"] = var["description"]
        if var.get("initial") and var["causality"] != "parameter":
            attrs["initial"] = var["initial"]
        model_variables.append(ET.Comment(f'Index of variable = "{index}"'))
        scalar = ET.SubElement(model_variables, "ScalarVariable", attrs)

        type_attrs = {}
        if var.get("declared_type"):
            type_attrs["declaredType"] = var["declared_type"]
        if var.get("quantity"):
            type_attrs["quantity"] = var["quantity"]
        if var.get("unit") and var["type"] == "Real":
            type_attrs["unit"] = var["unit"]
        for key in ("min", "max", "nominal"):
            if key in var:
                type_attrs[key] = _format_value(var["type"], var[key])
        if "start" in var:
            start = var["start"][element] if isinstance(var["start"], list) else var["start"]
            type_attrs["start"] = _format_value(var["type"], start)
        ET.SubElement(scalar, var["type"], type_attrs)

    # Omitting "dependencies" means an output may depend on all inputs.
    structure = ET.SubElement(root, "ModelStructure")
    outputs = [v for v in variables if v["causality"] == "output"]
    if outputs:
        outputs_el = ET.SubElement(structure, "Outputs")
        for var in outputs:
            for index in index_of[var["name"]]:
                ET.SubElement(outputs_el, "Unknown", _unknown(var, index, index_of))
    initial_unknowns = [
        v for v in variables
        if (v["causality"] == "output" and v.get("initial") != "exact")
        or v["causality"] == "calculatedParameter"
    ]
    if initial_unknowns:
        initial_el = ET.SubElement(structure, "InitialUnknowns")
        for index in sorted(i for v in initial_unknowns for i in index_of[v["name"]]):
            ET.SubElement(initial_el, "Unknown", {"index": str(index)})

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return tree


def _unknown(var, index, index_of):
    attrs = {"index": str(index)}
    if "depends_on" in var:
        attrs["dependencies"] = " ".join(str(i) for name in var["depends_on"] for i in index_of[name])
    return attrs


def _scalars(variables):
    """(variable, element, name) for each FMI 2 ScalarVariable: an array x with dimensions [2, 3]
    becomes x[1,1], x[1,2], ... x[2,3] (row-major, 1-based, FMI 2 "structured" naming)."""
    for var in variables:
        dims = var.get("dimensions")
        if not dims:
            yield var, 0, var["name"]
            continue
        for element, position in enumerate(itertools.product(*(range(1, d + 1) for d in dims))):
            yield var, element, f"{var['name']}[{','.join(map(str, position))}]"


LOG_CATEGORIES_FMI3 = [
    ("logStatusWarning", None),
    ("logStatusDiscard", None),
    ("logStatusError", None),
    ("logStatusFatal", None),
    ("logEvents", None),
    ("logUnifmuMessages",
     "Messages related to internal UniFMU functionality. "
     "Enabling this category is required for distributed UniFMUs."),
]


def build_model_description_fmi3(interface, model_name=None, author=None):
    """Return the FMI 3.0 Co-Simulation modelDescription.xml ElementTree for a fmugen interface spec."""
    variables = interface["variables"]
    clocks = interface.get("clocks", [])
    experiment = interface.get("experiment", {})
    can_state = "true" if interface.get("can_get_and_set_state", True) else "false"
    vr_of = {v["name"]: v["valueReference"] for v in [*variables, *clocks]}

    root = ET.Element("fmiModelDescription", {
        "fmiVersion": "3.0",
        "modelName": model_name or interface["model_name"],
        "instantiationToken": GUID_PLACEHOLDER,
        "description": interface.get("description", ""),
        "author": interface.get("author", "") if author is None else author,
        "generationTool": "fmugen + unifmu",
        "generationDateAndTime": build_time().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variableNamingConvention": "flat",
    })

    ET.SubElement(root, "CoSimulation", {
        "modelIdentifier": "unifmu",
        "needsExecutionTool": "true",
        "canBeInstantiatedOnlyOncePerProcess": "false",
        "canGetAndSetFMUState": can_state,
        "canSerializeFMUState": can_state,
        "canHandleVariableCommunicationStepSize": "false" if experiment.get("fixed_step") else "true",
        "hasEventMode": "true" if interface.get("has_event_mode") else "false",
        "canReturnEarlyAfterIntermediateUpdate": "false",
        "providesIntermediateUpdate": "false",
    })

    units = sorted({v["unit"] for v in variables if v.get("unit") and v["type"] in FLOAT_TYPES})
    if units:
        unit_defs = ET.SubElement(root, "UnitDefinitions")
        for unit in units:
            ET.SubElement(unit_defs, "Unit", {"name": unit})

    type_definitions = interface.get("type_definitions", {})
    if type_definitions:
        type_defs = ET.SubElement(root, "TypeDefinitions")
        for name, definition in type_definitions.items():
            enumeration = ET.SubElement(type_defs, "EnumerationType", {"name": name})
            for value, item in enumerate(definition["items"], start=1):
                ET.SubElement(enumeration, "Item", {"name": item, "value": str(value)})

    log_categories = ET.SubElement(root, "LogCategories")
    for name, description in LOG_CATEGORIES_FMI3:
        attrs = {"name": name}
        if description:
            attrs["description"] = description
        ET.SubElement(log_categories, "Category", attrs)

    experiment_attrs = {
        xml_name: _format_value("Real", float(experiment[key]))
        for key, xml_name in EXPERIMENT_ATTRIBUTES.items() if key in experiment
    }
    if experiment_attrs:
        ET.SubElement(root, "DefaultExperiment", experiment_attrs)

    model_variables = ET.SubElement(root, "ModelVariables")
    for var in variables:
        attrs = {
            "name": var["name"],
            "valueReference": str(var["valueReference"]),
            "causality": var["causality"],
            "variability": var["variability"],
        }
        for key, xml_name in (("description", "description"), ("declared_type", "declaredType"),
                              ("quantity", "quantity")):
            if var.get(key):
                attrs[xml_name] = var[key]
        if var.get("initial") and var["causality"] not in ("parameter", "structuralParameter"):
            attrs["initial"] = var["initial"]
        if var.get("unit") and var["type"] in FLOAT_TYPES:
            attrs["unit"] = var["unit"]
        for key in ("min", "max", "nominal"):
            if key in var:
                attrs[key] = _format_value(var["type"], var[key])
        if var.get("clocks"):
            attrs["clocks"] = " ".join(str(vr_of[c]) for c in var["clocks"])
        start = var.get("start")
        start_children = []
        if start is not None:
            values = start if isinstance(start, list) else [start]
            if var["type"] in ("String", "Binary"):
                start_children = values
            else:
                attrs["start"] = " ".join(_format_value(var["type"], v) for v in values)
        element = ET.SubElement(model_variables, "Float64" if var["type"] == "Real" else var["type"], attrs)
        for value in start_children:
            ET.SubElement(element, "Start", {"value": str(value)})
        for d in var.get("dimensions", []):
            ET.SubElement(element, "Dimension",
                          {"valueReference": str(vr_of[d])} if isinstance(d, str) else {"start": str(d)})

    for clock in clocks:
        attrs = {
            "name": clock["name"],
            "valueReference": str(clock["valueReference"]),
            "causality": clock["causality"],
            "variability": "discrete",
            "intervalVariability": clock["interval_variability"],
        }
        if clock.get("description"):
            attrs["description"] = clock["description"]
        if "interval" in clock:
            attrs["intervalDecimal"] = _format_value("Real", clock["interval"])
        if clock.get("shift"):
            attrs["shiftDecimal"] = _format_value("Real", clock["shift"])
        ET.SubElement(model_variables, "Clock", attrs)

    structure = ET.SubElement(root, "ModelStructure")
    outputs = [v for v in [*variables, *clocks] if v["causality"] == "output"]
    for var in sorted(outputs, key=lambda v: v["valueReference"]):
        attrs = {"valueReference": str(var["valueReference"])}
        if "depends_on" in var:
            attrs["dependencies"] = " ".join(str(vr_of[name]) for name in var["depends_on"])
        ET.SubElement(structure, "Output", attrs)
    for var in variables:
        if var.get("clocks"):
            continue  # clocked variables only get values when their clock ticks
        if (var["causality"] == "output" and var.get("initial") != "exact") or var["causality"] == "calculatedParameter":
            ET.SubElement(structure, "InitialUnknown", {"valueReference": str(var["valueReference"])})

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return tree


def write_model_description(interface, path, **kwargs):
    build = build_model_description_fmi3 if interface.get("fmi_version", 2) == 3 else build_model_description
    tree = build(interface, **kwargs)
    tree.write(Path(path), encoding="utf-8", xml_declaration=True)


def stamp_guid(fmu_dir):
    """Replace GUID_PLACEHOLDER in fmu_dir's modelDescription.xml by a UUID hashed from every file of the FMU."""
    fmu_dir = Path(fmu_dir)
    digest = hashlib.sha256()
    for file in sorted(f for f in fmu_dir.rglob("*") if f.is_file() and "__pycache__" not in f.parts):
        digest.update(file.relative_to(fmu_dir).as_posix().encode() + b"/")
        digest.update(hashlib.sha256(file.read_bytes()).digest())
    description = fmu_dir / "modelDescription.xml"
    token = "{" + str(uuid.uuid5(GUID_NAMESPACE, digest.hexdigest())) + "}"
    description.write_bytes(description.read_bytes().replace(GUID_PLACEHOLDER.encode(), token.encode()))
    return token
