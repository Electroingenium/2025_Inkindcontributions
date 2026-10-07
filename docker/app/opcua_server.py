"""OPC UA server: one Inputs/ and one Outputs/ node per FMU variable, built from modelDescription.xml."""
import logging
import os
import time

from fmu_io import NAMESPACE_URI, read_fmu
from opcua import Server

FMU_PATH = os.getenv("FMU_PATH", "/model/model.fmu")
ENDPOINT = os.getenv("OPCUA_BIND_ENDPOINT", "opc.tcp://0.0.0.0:4840")


def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("opcua_server")
    logging.getLogger("opcua").setLevel(logging.WARNING)

    md, inputs, outputs = read_fmu(FMU_PATH)
    logger.info(f"{md.modelName} (FMI {md.fmiVersion}): {len(inputs)} inputs, {len(outputs)} outputs")

    server = Server()
    server.set_endpoint(ENDPOINT)
    server.set_server_name("EIUM_OPCUA_Server")
    idx = server.register_namespace(NAMESPACE_URI)
    objects = server.get_objects_node()

    # Inputs: written by the Streamlit UI, read by the FMU runner.
    # Outputs: written by the FMU runner, read by the Streamlit UI.
    for folder_name, variables in (("Inputs", inputs), ("Outputs", outputs)):
        folder = objects.add_folder(idx, folder_name)
        for var in variables:
            node = folder.add_variable(idx, var.name, var.variant(var.start))
            node.set_writable(True)
            logger.info(f" - {folder_name}/{var.name} ({var.suffix}) = {var.start}")

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
