import time, os, logging, shutil
import pandas as pd
from fmpy import read_model_description, extract
from fmpy.fmi2 import FMU2Slave
from opcua import Client as OPCClient, ua

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fmu_runner_opc")

# === CONFIG ===
FMU_PATH = os.getenv("FMU_PATH", "/app/model.fmu")

if not os.path.exists(FMU_PATH):
    raise FileNotFoundError(f"FMU_PATH does not exist: {FMU_PATH}")

if os.path.isdir(FMU_PATH):
    raise IsADirectoryError(
        f"FMU_PATH points to a directory, expected a .fmu file: {FMU_PATH} "
        f"(Did you accidentally mount a folder instead of the .fmu file?)"
    )

RESULTS_DIR = os.getenv("RESULTS_DIR", "/results")
START_TIME = float(os.getenv("START_TIME", 0.0))
STOP_TIME = float(os.getenv("STOP_TIME", 10.0))
STEP_SIZE = float(os.getenv("STEP_SIZE", 1.0))
OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")
NAMESPACE_URI = os.getenv("OPCUA_NAMESPACE", "urn:eium:opcua:fmu")

def simulate_and_publish():
    # === OPC UA CLIENT ===
    import time
    time.sleep(float(os.getenv("OPC_WAIT", 5)))
    opc = OPCClient(OPCUA_ENDPOINT)
    opc.connect()
    idx = opc.get_namespace_index(NAMESPACE_URI)
    fmu_node = opc.get_objects_node().get_child([ua.QualifiedName("FMU", idx)])
    logger.info(f"Connected to OPC UA server {OPCUA_ENDPOINT}")

    # Map OPC UA variable handles
    opc_nodes = {
        n: fmu_node.get_child([ua.QualifiedName(n, idx)])
        for n in ["energy_balance","mass_balance","mdot_air_in","mdot_air_out","Q_in","Q_out"]
    }

    # === FMU INIT ===
    model_description = read_model_description(FMU_PATH)
    unzipdir = extract(FMU_PATH)
    vrs = {v.name: v.valueReference for v in model_description.modelVariables}
    output_names = list(opc_nodes.keys())

    fmu = FMU2Slave(
        guid=model_description.guid,
        unzipDirectory=unzipdir,
        modelIdentifier=model_description.coSimulation.modelIdentifier,
        instanceName='instance1'
    )
    fmu.instantiate()
    fmu.setupExperiment(startTime=START_TIME)
    fmu.enterInitializationMode()
    fmu.exitInitializationMode()

    logger.info("🚀 Starting FMU simulation loop")
    sim_time = START_TIME
    results = []

    try:
        while sim_time <= STOP_TIME:
            fmu.doStep(currentCommunicationPoint=sim_time, communicationStepSize=STEP_SIZE)
            outputs = fmu.getReal([vrs[n] for n in output_names])
            row = {"time": sim_time}
            row.update(dict(zip(output_names, outputs)))
            results.append(row)

            # Publica valores en OPC UA
            for name, val in zip(output_names, outputs):
                try:
                    opc_nodes[name].set_value(ua.Variant(float(val), ua.VariantType.Double))
                except Exception as e:
                    logger.warning(f"Failed to update {name}: {e}")

            sim_time += STEP_SIZE
            time.sleep(0.2)

        logger.info("✅ Simulation complete.")

    finally:
        fmu.terminate()
        fmu.freeInstance()
        opc.disconnect()
        shutil.rmtree(unzipdir, ignore_errors=True)

        df = pd.DataFrame(results)
        csv_path = os.path.join(RESULTS_DIR, "simulation_outputs.csv")
        df.to_csv(csv_path, index=False)
        logger.info(f"📊 Results saved to {csv_path}")

if __name__ == "__main__":
    simulate_and_publish()
