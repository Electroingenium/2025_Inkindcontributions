"""One simulation run: steps the FMU with FMPy, exchanging inputs and outputs through OPC UA.

Each step reads Inputs/ from OPC UA, steps the FMU and writes Outputs/ back. At the end the
results are printed to stdout between RESULTS_BEGIN/RESULTS_END, which is how the UI gets
them from a container or pod (also one offloaded to another cluster by Liqo), and written
to RESULTS_DIR/<RUN_NAME>.csv when RESULTS_DIR is set.
"""
import io
import logging
import os
import shutil
import sys
import time

import pandas as pd
from fmpy import extract
from fmpy.fmi2 import FMU2Slave
from fmpy.fmi3 import FMU3Slave
from opcua import Client as OPCClient, ua

from fmu_io import NAMESPACE_URI, RESULTS_BEGIN, RESULTS_END, experiment, read_fmu

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("fmu_runner")
logging.getLogger("opcua").setLevel(logging.WARNING)

FMU_PATH = os.getenv("FMU_PATH", "/model/model.fmu")
RESULTS_DIR = os.getenv("RESULTS_DIR", "")
RUN_NAME = os.getenv("RUN_NAME", "simulation_outputs")
START_TIME = float(os.getenv("START_TIME", 0.0))
STOP_TIME = float(os.getenv("STOP_TIME", 10.0))
STEP_SIZE = float(os.getenv("STEP_SIZE", 1.0))
STEP_DELAY = float(os.getenv("STEP_DELAY", 0.5))  # wall-clock pause between steps [s]
OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")
OPC_TIMEOUT = float(os.getenv("OPC_TIMEOUT", 60))  # how long to retry connecting [s]


def connect(endpoint):
    """Connect to the OPC UA server, retrying while it (or the network to it) comes up."""
    deadline = time.monotonic() + OPC_TIMEOUT
    while True:
        opc = OPCClient(endpoint)
        try:
            opc.connect()
            return opc
        except Exception as e:
            if time.monotonic() > deadline:
                raise
            logger.info(f"Waiting for OPC UA server {endpoint}: {e}")
            time.sleep(2)


def folder_nodes(opc, folder_name):
    """{browse name: node} for the variables in an OPC UA folder."""
    ns_idx = opc.get_namespace_index(NAMESPACE_URI)
    folder = opc.get_objects_node().get_child([ua.QualifiedName(folder_name, ns_idx)])
    return {child.get_browse_name().Name: child for child in folder.get_children()}


class Slave:
    """FMI 2 / FMI 3 get and set by fmpy suffix, scalar or array."""

    def __init__(self, md, unzipdir):
        self.fmi3 = md.fmiVersion.startswith("3")
        cls = FMU3Slave if self.fmi3 else FMU2Slave
        self.fmu = cls(guid=md.guid, unzipDirectory=unzipdir,
                       modelIdentifier=md.coSimulation.modelIdentifier, instanceName="instance1")

    def set(self, var, value):
        values = list(value) if var.size is not None else [value]
        values = [var.py_type(v) for v in values]
        getattr(self.fmu, "set" + var.suffix)([var.vr], values)

    def get(self, var):
        getter = getattr(self.fmu, "get" + var.suffix)
        values = getter([var.vr], nValues=var.size or 1) if self.fmi3 else getter([var.vr])
        if var.py_type is str:
            values = [v.decode() if isinstance(v, bytes) else v for v in values]
        values = [var.py_type(v) for v in values]
        return values if var.size is not None else values[0]

    def start(self, start_time):
        self.fmu.instantiate()
        if self.fmi3:
            self.fmu.enterInitializationMode(startTime=start_time)
        else:
            self.fmu.setupExperiment(startTime=start_time)
            self.fmu.enterInitializationMode()

    def step(self, t, h):
        """Do a step; True if the FMU asked to stop the simulation."""
        result = self.fmu.doStep(currentCommunicationPoint=t, communicationStepSize=h)
        return bool(self.fmi3 and result[1])   # FMI 3: (eventHandlingNeeded, terminateSimulation, ...)


def columns(var, value):
    """CSV columns of one value: name, or name[1]..name[n] for an array."""
    if var.size is None:
        return {var.name: value}
    return {f"{var.name}[{i + 1}]": v for i, v in enumerate(value)}


def simulate_and_publish():
    md, inputs, outputs = read_fmu(FMU_PATH)
    logger.info(f"{md.modelName} (FMI {md.fmiVersion})")
    logger.info(f"Inputs: {[v.name for v in inputs]}")
    logger.info(f"Outputs: {[v.name for v in outputs]}")
    step_size = STEP_SIZE
    _, _, default_step, fixed_step = experiment(md)
    if fixed_step and abs(step_size - default_step) > 1e-12:
        logger.warning(f"The FMU only takes steps of {default_step:g}; using that instead of STEP_SIZE={step_size:g}")
        step_size = default_step

    opc = connect(OPCUA_ENDPOINT)
    logger.info(f"Connected to OPC UA server {OPCUA_ENDPOINT}")
    input_nodes = folder_nodes(opc, "Inputs")
    output_nodes = folder_nodes(opc, "Outputs")
    for v in inputs:
        if v.name not in input_nodes:
            logger.warning(f"Input '{v.name}' has no OPC UA node; it keeps its start value")

    unzipdir = extract(FMU_PATH)
    slave = Slave(md, unzipdir)

    def apply_inputs(variables):
        values = {}
        for var in variables:
            node = input_nodes.get(var.name)
            if node is None:
                continue
            try:
                value = node.get_value()
                slave.set(var, value)
                values.update(columns(var, value))
            except Exception as e:
                logger.warning(f"Failed to apply input {var.name}: {e}")
        return values

    def publish_outputs():
        values = {}
        for var in outputs:
            try:
                value = slave.get(var)
                values.update(columns(var, value))
                node = output_nodes.get(var.name)
                if node is not None:
                    node.set_value(var.variant(value))
            except Exception as e:
                logger.warning(f"Failed to update output {var.name}: {e}")
        return values

    results = []
    try:
        slave.start(START_TIME)
        # Every input and parameter can be set during initialization; afterwards only
        # inputs and tunable parameters.
        row = {"time": START_TIME, **apply_inputs(inputs)}
        slave.fmu.exitInitializationMode()
        results.append({**row, **publish_outputs()})

        logger.info("Starting FMU simulation loop")
        tunable = [v for v in inputs if v.tunable]
        t = START_TIME
        while t < STOP_TIME - 1e-9 * max(1.0, abs(STOP_TIME)):
            h = step_size if fixed_step else min(step_size, STOP_TIME - t)
            row = apply_inputs(tunable)
            stop = slave.step(t, h)
            t = round(t + h, 12)
            out = publish_outputs()
            results.append({"time": t, **row, **out})
            logger.info(f"[t={t:g}] Outputs: {out}")
            if stop:
                logger.info("The FMU stopped the simulation")
                break
            time.sleep(STEP_DELAY)
        logger.info("Simulation complete.")
        slave.fmu.terminate()
    finally:
        # Cleanup must not hide the error that got us here (e.g. a failed instantiate)
        for cleanup in (slave.fmu.freeInstance, opc.disconnect):
            try:
                cleanup()
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")
        shutil.rmtree(unzipdir, ignore_errors=True)

        df = pd.DataFrame(results).ffill()
        if RESULTS_DIR:
            csv_path = os.path.join(RESULTS_DIR, f"{RUN_NAME}.csv")
            df.to_csv(csv_path, index=False)
            logger.info(f"Results saved to {csv_path}")
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        sys.stderr.flush()
        print(RESULTS_BEGIN, buf.getvalue().rstrip("\n"), RESULTS_END, sep="\n", flush=True)


if __name__ == "__main__":
    simulate_and_publish()
