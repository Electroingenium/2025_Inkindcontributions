"""modelDescription.xml (FMI 2.0 Co-Simulation) from a fmugen interface spec."""
import math
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

EXPERIMENT_ATTRIBUTES = {
    "start_time": "startTime", "stop_time": "stopTime",
    "tolerance": "tolerance", "step_size": "stepSize",
}


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
        "guid": "{" + str(uuid.uuid4()) + "}",
        "description": interface.get("description", ""),
        "author": interface.get("author", "") if author is None else author,
        "generationTool": "fmugen + unifmu",
        "generationDateAndTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variableNamingConvention": "flat",
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
    index_of = {}
    for index, var in enumerate(variables, start=1):
        index_of[var["name"]] = index
        attrs = {
            "name": var["name"],
            "valueReference": str(var["valueReference"]),
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
            type_attrs["start"] = _format_value(var["type"], var["start"])
        ET.SubElement(scalar, var["type"], type_attrs)

    # Omitting "dependencies" means an output may depend on all inputs.
    structure = ET.SubElement(root, "ModelStructure")
    outputs = [v for v in variables if v["causality"] == "output"]
    if outputs:
        outputs_el = ET.SubElement(structure, "Outputs")
        for var in outputs:
            ET.SubElement(outputs_el, "Unknown", _unknown(var, index_of))
    initial_unknowns = [
        v for v in variables
        if (v["causality"] == "output" and v.get("initial") != "exact")
        or v["causality"] == "calculatedParameter"
    ]
    if initial_unknowns:
        initial_el = ET.SubElement(structure, "InitialUnknowns")
        for var in sorted(initial_unknowns, key=lambda v: index_of[v["name"]]):
            ET.SubElement(initial_el, "Unknown", {"index": str(index_of[var["name"]])})

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return tree


def _unknown(var, index_of):
    attrs = {"index": str(index_of[var["name"]])}
    if "depends_on" in var:
        attrs["dependencies"] = " ".join(str(index_of[name]) for name in var["depends_on"])
    return attrs


def write_model_description(interface, path, **kwargs):
    tree = build_model_description(interface, **kwargs)
    tree.write(Path(path), encoding="utf-8", xml_declaration=True)
