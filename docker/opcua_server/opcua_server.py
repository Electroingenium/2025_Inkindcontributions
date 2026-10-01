import os
import time
import logging
import zipfile
import xml.etree.ElementTree as ET
from opcua import Server, ua

# ==========================================================
# CONFIGURATION
# ==========================================================
FMU_PATH = os.getenv("FMU_PATH", "/model/model.fmu")
ENDPOINT = os.getenv("OPCUA_BIND_ENDPOINT", "opc.tcp://0.0.0.0:4840")
NAMESPACE_URI = "urn:eium:opcua:fmu"

VARIANT_TYPES = {
    "Real": ua.VariantType.Double,
    "Integer": ua.VariantType.Int32,
    "Boolean": ua.VariantType.Boolean,
    "String": ua.VariantType.String,
}
DEFAULTS = {"Real": 0.0, "Integer": 0, "Boolean": False, "String": ""}


def read_fmu_variables(fmu_path):
    """Return the FMU's inputs/parameters and outputs as (name, type, start) lists."""
    with zipfile.ZipFile(fmu_path) as fmu:
        root = ET.fromstring(fmu.read("modelDescription.xml"))

    inputs, outputs = [], []
    for sv in root.iter("ScalarVariable"):
        type_el = next(el for el in sv if el.tag in VARIANT_TYPES)
        fmi_type = type_el.tag
        start = type_el.get("start")
        if start is None:
            value = DEFAULTS[fmi_type]
        elif fmi_type == "Real":
            value = float(start)
        elif fmi_type == "Integer":
            value = int(start)
        elif fmi_type == "Boolean":
            value = start == "true"
        else:
            value = start

        causality = sv.get("causality", "local")
        if causality in ("input", "parameter"):
            inputs.append((sv.get("name"), fmi_type, value))
        elif causality == "output":
            outputs.append((sv.get("name"), fmi_type, value))
    return inputs, outputs


def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("opcua_server")

    inputs, outputs = read_fmu_variables(FMU_PATH)
    logger.info(f"Loaded {len(inputs)} inputs and {len(outputs)} outputs from {FMU_PATH}")

    server = Server()
    server.set_endpoint(ENDPOINT)
    server.set_server_name("EIUM_OPCUA_Server")
    idx = server.register_namespace(NAMESPACE_URI)
    objects = server.get_objects_node()

    # Inputs: written by the Streamlit UI, read by the FMU runner.
    # Outputs: written by the FMU runner, read by the Streamlit UI.
    for folder_name, variables in (("Inputs", inputs), ("Outputs", outputs)):
        folder = objects.add_folder(idx, folder_name)
        for name, fmi_type, value in variables:
            node = folder.add_variable(idx, name, ua.Variant(value, VARIANT_TYPES[fmi_type]))
            node.set_writable(True)
            logger.info(f" - {folder_name}/{name} ({fmi_type}) = {value}")

    server.start()
    logger.info(f"OPC UA server started at {ENDPOINT} (namespace {NAMESPACE_URI}, index {idx})")

    try:
        while True:
            time.sleep(1)
    finally:
        server.stop()
        logger.info("OPC UA server stopped.")


if __name__ == "__main__":
    main()
