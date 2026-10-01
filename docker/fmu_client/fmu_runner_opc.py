import os
import time
import logging
import shutil
import pandas as pd
from fmpy import read_model_description, extract
from fmpy.fmi2 import FMU2Slave
from opcua import Client as OPCClient, ua

# =====================================================
# LOGGING CONFIG
# =====================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fmu_runner_opc")

# =====================================================
# CONFIGURATION
# =====================================================
FMU_PATH = os.getenv("FMU_PATH", "/app/model.fmu")
RESULTS_DIR = os.getenv("RESULTS_DIR", "/results")
START_TIME = float(os.getenv("START_TIME", 0.0))
STOP_TIME = float(os.getenv("STOP_TIME", 10.0))
STEP_SIZE = float(os.getenv("STEP_SIZE", 1.0))
STEP_DELAY = float(os.getenv("STEP_DELAY", 0.5))  # wall-clock pause between steps [s]
OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")
NAMESPACE_URI = "urn:eium:opcua:fmu"

if not os.path.exists(FMU_PATH):
    raise FileNotFoundError(f"FMU_PATH does not exist: {FMU_PATH}")

if os.path.isdir(FMU_PATH):
    raise IsADirectoryError(
        f"FMU_PATH points to a directory, expected a .fmu file: {FMU_PATH}"
    )

VARIANT_TYPES = {
    "Real": ua.VariantType.Double,
    "Integer": ua.VariantType.Int32,
    "Boolean": ua.VariantType.Boolean,
    "String": ua.VariantType.String,
}


def opc_folder_nodes(opc, folder_name):
    """Return {browse name: node} for the variables in an OPC UA folder."""
    ns_idx = opc.get_namespace_index(NAMESPACE_URI)
    folder = opc.get_objects_node().get_child([ua.QualifiedName(folder_name, ns_idx)])
    return {child.get_browse_name().Name: child for child in folder.get_children()}


def set_fmu_value(fmu, var, value):
    setter = {
        "Real": fmu.setReal,
        "Integer": fmu.setInteger,
        "Boolean": fmu.setBoolean,
        "String": fmu.setString,
    }[var.type]
    if var.type == "String":
        value = str(value).encode()
    setter([var.valueReference], [value])


def get_fmu_value(fmu, var):
    getter = {
        "Real": fmu.getReal,
        "Integer": fmu.getInteger,
        "Boolean": fmu.getBoolean,
        "String": fmu.getString,
    }[var.type]
    value = getter([var.valueReference])[0]
    if var.type == "String":
        value = value.decode()
    elif var.type == "Boolean":
        value = bool(value)
    return value


# =====================================================
# MAIN FUNCTION
# =====================================================

def simulate_and_publish():
    """Run FMU simulation and exchange data via OPC UA"""

    # Small delay to ensure the OPC UA server is ready
    time.sleep(float(os.getenv("OPC_WAIT", 5)))

    # -------------------------------------------------
    # READ FMU INTERFACE
    # -------------------------------------------------
    model_description = read_model_description(FMU_PATH)
    fmu_inputs = [v for v in model_description.modelVariables if v.causality in ("input", "parameter")]
    fmu_outputs = [v for v in model_description.modelVariables if v.causality == "output"]
    logger.info(f"FMU inputs: {[v.name for v in fmu_inputs]}")
    logger.info(f"FMU outputs: {[v.name for v in fmu_outputs]}")

    # -------------------------------------------------
    # CONNECT TO OPC UA SERVER
    # -------------------------------------------------
    opc = OPCClient(OPCUA_ENDPOINT)
    opc.connect()
    logger.info(f"Connected to OPC UA server {OPCUA_ENDPOINT}")

    input_nodes = opc_folder_nodes(opc, "Inputs")
    output_nodes = opc_folder_nodes(opc, "Outputs")

    for v in fmu_inputs:
        if v.name not in input_nodes:
            logger.warning(f"FMU input '{v.name}' has no OPC UA node; it keeps its start value")
    for v in fmu_outputs:
        if v.name not in output_nodes:
            logger.warning(f"FMU output '{v.name}' has no OPC UA node; it is only saved to CSV")

    def apply_opc_inputs():
        values = {}
        for var in fmu_inputs:
            node = input_nodes.get(var.name)
            if node is None:
                continue
            try:
                value = node.get_value()
                set_fmu_value(fmu, var, value)
                values[var.name] = value
            except Exception as e:
                logger.warning(f"Failed to apply input {var.name}: {e}")
        return values

    def publish_outputs():
        values = {}
        for var in fmu_outputs:
            try:
                value = get_fmu_value(fmu, var)
                values[var.name] = value
                node = output_nodes.get(var.name)
                if node is not None:
                    node.set_value(ua.Variant(value, VARIANT_TYPES[var.type]))
            except Exception as e:
                logger.warning(f"Failed to update output {var.name}: {e}")
        return values

    # -------------------------------------------------
    # INITIALIZE FMU
    # -------------------------------------------------
    unzipdir = extract(FMU_PATH)

    fmu = FMU2Slave(
        guid=model_description.guid,
        unzipDirectory=unzipdir,
        modelIdentifier=model_description.coSimulation.modelIdentifier,
        instanceName='instance1'
    )

    fmu.instantiate()
    fmu.setupExperiment(startTime=START_TIME)
    fmu.enterInitializationMode()
    apply_opc_inputs()
    fmu.exitInitializationMode()

    logger.info("Starting FMU simulation loop")
    sim_time = START_TIME
    results = []

    # -------------------------------------------------
    # SIMULATION LOOP
    # -------------------------------------------------
    try:
        while sim_time <= STOP_TIME:
            inputs = apply_opc_inputs()

            fmu.doStep(currentCommunicationPoint=sim_time, communicationStepSize=STEP_SIZE)

            outputs = publish_outputs()

            row = {"time": sim_time}
            row.update(inputs)
            row.update(outputs)
            results.append(row)

            logger.info(f"[t={sim_time:.1f}] Outputs: {outputs}")
            sim_time += STEP_SIZE
            time.sleep(STEP_DELAY)

        logger.info("Simulation complete.")

    finally:
        fmu.terminate()
        fmu.freeInstance()
        opc.disconnect()
        shutil.rmtree(unzipdir, ignore_errors=True)

        # Save results to CSV
        df = pd.DataFrame(results)
        csv_path = os.path.join(RESULTS_DIR, "simulation_outputs.csv")
        df.to_csv(csv_path, index=False)
        logger.info(f"Results saved to {csv_path}")


if __name__ == "__main__":
    simulate_and_publish()
