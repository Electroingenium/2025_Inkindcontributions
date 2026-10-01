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


def _format_start(fmi_type, value):
    if fmi_type == "Boolean":
        return "true" if value else "false"
    return str(value)


def build_model_description(interface, model_name=None, author=""):
    """Return the modelDescription.xml ElementTree for a fmugen interface spec."""
    variables = interface["variables"]

    root = ET.Element("fmiModelDescription", {
        "fmiVersion": "2.0",
        "modelName": model_name or interface["model_module"],
        "guid": "{" + str(uuid.uuid4()) + "}",
        "description": interface.get("model_doc", "").splitlines()[0] if interface.get("model_doc") else "",
        "author": author,
        "generationTool": "fmugen + unifmu",
        "generationDateAndTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variableNamingConvention": "flat",
    })

    ET.SubElement(root, "CoSimulation", {
        "modelIdentifier": "unifmu",
        "needsExecutionTool": "true",
        "canNotUseMemoryManagementFunctions": "true",
        "canHandleVariableCommunicationStepSize": "true",
        "canGetAndSetFMUstate": "true",
        "canSerializeFMUstate": "true",
    })

    units = sorted({v["unit"] for v in variables if v.get("unit")})
    if units:
        unit_defs = ET.SubElement(root, "UnitDefinitions")
        for unit in units:
            ET.SubElement(unit_defs, "Unit", {"name": unit})

    log_categories = ET.SubElement(root, "LogCategories")
    for name, description in LOG_CATEGORIES:
        attrs = {"name": name}
        if description:
            attrs["description"] = description
        ET.SubElement(log_categories, "Category", attrs)

    model_variables = ET.SubElement(root, "ModelVariables")
    output_indices = []
    for index, var in enumerate(variables, start=1):
        attrs = {
            "name": var["name"],
            "valueReference": str(var["valueReference"]),
            "causality": var["causality"],
            "variability": var["variability"],
        }
        if var.get("description"):
            attrs["description"] = var["description"]
        if var["causality"] == "output":
            attrs["initial"] = "calculated"
            output_indices.append(index)
        model_variables.append(ET.Comment(f'Index of variable = "{index}"'))
        scalar = ET.SubElement(model_variables, "ScalarVariable", attrs)

        type_attrs = {}
        if "start" in var:
            type_attrs["start"] = _format_start(var["type"], var["start"])
        if var.get("unit") and var["type"] == "Real":
            type_attrs["unit"] = var["unit"]
        ET.SubElement(scalar, var["type"], type_attrs)

    # Omitting "dependencies" means each output may depend on all inputs.
    structure = ET.SubElement(root, "ModelStructure")
    outputs = ET.SubElement(structure, "Outputs")
    initial_unknowns = ET.SubElement(structure, "InitialUnknowns")
    for index in output_indices:
        ET.SubElement(outputs, "Unknown", {"index": str(index)})
        ET.SubElement(initial_unknowns, "Unknown", {"index": str(index)})

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return tree


def write_model_description(interface, path, **kwargs):
    tree = build_model_description(interface, **kwargs)
    tree.write(Path(path), encoding="utf-8", xml_declaration=True)
