
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
OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")

if not os.path.exists(FMU_PATH):
    raise FileNotFoundError(f"FMU_PATH does not exist: {FMU_PATH}")

if os.path.isdir(FMU_PATH):
    raise IsADirectoryError(
        f"FMU_PATH points to a directory, expected a .fmu file: {FMU_PATH}"
    )

# =====================================================
# MAIN FUNCTION
# =====================================================

def simulate_and_publish():
    """Run FMU simulation and exchange data via OPC UA"""

    # Small delay to ensure the OPC UA server is ready
    time.sleep(float(os.getenv("OPC_WAIT", 5)))

    # -------------------------------------------------
    # CONNECT TO OPC UA SERVER
    # -------------------------------------------------
    opc = OPCClient(OPCUA_ENDPOINT)
    opc.connect()
    logger.info(f"Connected to OPC UA server {OPCUA_ENDPOINT}")

    # Get Objects node
    objects = opc.get_objects_node()
    vars_all = [v.get_browse_name().Name for v in objects.get_children()]
    logger.info(f"Available OPC UA variables: {vars_all}")

    # Define groups
    calc_vars = [
        "energy_balance", "mass_balance", "mdot_air_in", "mdot_air_out", "Q_in", "Q_out"
    ]
    control_vars = [
        "regen_heater_power", "regen_vfr_setpoint", "regen_target_temp"
    ]
    aux_vars = [
        "temp_1", "temp_5", "temp_10",
        "vfr_1", "vfr_5", "vfr_13",
        "RH_1", "RH_6", "RH_9"
    ]

    # # Get OPC nodes by name
    # def get_node(name):
    #     try:
    #         return objects.get_child(f"0:{name}")
    #     except Exception:
    #         logger.warning(f"⚠️ Could not find node '{name}' in OPC UA server")
    #         return None

    # calc_nodes = {n: get_node(n) for n in calc_vars}
    # control_nodes = {n: get_node(n) for n in control_vars}
    # aux_nodes = {n: get_node(n) for n in aux_vars}
    # Get OPC nodes by name
    # Detect namespace index automatically
    namespaces = opc.get_namespace_array()
    logger.info(f"Namespaces: {namespaces}")
    try:
        ns_idx = opc.get_namespace_index("urn:eium:opcua:fmu")
    except Exception:
        ns_idx = 2  # fallback si no lo encuentra

    logger.info(f"Using namespace index: {ns_idx}")

    # Get OPC nodes by name
    def get_node(name):
        try:
            return objects.get_child([ua.QualifiedName(name, ns_idx)])
        except Exception:
            logger.warning(f"⚠️ Could not find node '{name}' in OPC UA server")
            return None

    calc_nodes = {n: get_node(n) for n in calc_vars}
    control_nodes = {n: get_node(n) for n in control_vars}
    aux_nodes = {n: get_node(n) for n in aux_vars}



    # -------------------------------------------------
    # INITIALIZE FMU
    # -------------------------------------------------
    model_description = read_model_description(FMU_PATH)
    unzipdir = extract(FMU_PATH)
    vrs = {v.name: v.valueReference for v in model_description.modelVariables}

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

    # -------------------------------------------------
    # SIMULATION LOOP
    # -------------------------------------------------
    try:
        while sim_time <= STOP_TIME:
            # Read setpoints and auxiliaries from OPC UA
            inputs = {}
            for name, node in {**control_nodes, **aux_nodes}.items():
                if node is not None:
                    try:
                        val = node.get_value()
                        inputs[name] = float(val)
                    except Exception as e:
                        logger.warning(f"Failed to read {name}: {e}")

            # Apply inputs (if variables exist in FMU)
            for name, val in inputs.items():
                if name in vrs:
                    fmu.setReal([vrs[name]], [val])

            # Step simulation
            fmu.doStep(currentCommunicationPoint=sim_time, communicationStepSize=STEP_SIZE)

            # Read outputs from FMU
            outputs = {}
            for name in calc_vars:
                if name in vrs:
                    try:
                        value = float(fmu.getReal([vrs[name]])[0])
                        outputs[name] = value
                        if calc_nodes[name] is not None:
                            calc_nodes[name].set_value(ua.Variant(value, ua.VariantType.Double))
                    except Exception as e:
                        logger.warning(f"Failed to update {name}: {e}")

            # Save step result
            row = {"time": sim_time}
            row.update(inputs)
            row.update(outputs)
            results.append(row)

            logger.info(f"[t={sim_time:.1f}] Outputs: {outputs}")
            sim_time += STEP_SIZE
            time.sleep(0.5)

        logger.info("✅ Simulation complete.")

    finally:
        fmu.terminate()
        fmu.freeInstance()
        opc.disconnect()
        shutil.rmtree(unzipdir, ignore_errors=True)

        # Save results to CSV
        df = pd.DataFrame(results)
        csv_path = os.path.join(RESULTS_DIR, "simulation_outputs.csv")
        df.to_csv(csv_path, index=False)
        logger.info(f"📊 Results saved to {csv_path}")


if __name__ == "__main__":
    simulate_and_publish()

