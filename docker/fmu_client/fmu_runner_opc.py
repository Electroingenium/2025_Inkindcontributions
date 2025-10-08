import os, time, shutil, logging
from pathlib import Path

import pandas as pd
from fmpy import read_model_description, extract
from fmpy.fmi2 import FMU2Slave

from opcua import Client as OPCClient, ua

# ====== CONFIG ======
FMU_PATH = Path(os.getenv("FMU_PATH", "/app/model.fmu")).resolve()
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "/results"))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_CSV = RESULTS_DIR / "simulation_inputs_outputs.csv"
PLOT_PDF   = RESULTS_DIR / "simulation_plots.pdf"
START_TIME = float(os.getenv("START_TIME", "0.0"))
STOP_TIME  = float(os.getenv("STOP_TIME", "10.0"))
STEP_SIZE  = float(os.getenv("STEP_SIZE", "1.0"))

# OPC UA
OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")
NAMESPACE_URI  = os.getenv("OPCUA_NAMESPACE", "urn:eium:opcua:fmu")

# Define las salidas que quieres registrar/publicar (ajusta a tu FMU)
DEFAULT_OUTPUTS = ["mass_balance", "energy_balance", "mdot_air_in", "mdot_air_out", "Q_in", "Q_out"]

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fmu_runner_opc")

# ====== OPC helpers ======
def get_idx(client):
    return client.get_namespace_index(NAMESPACE_URI)

def get_node(client, name):
    root = client.get_root_node()
    idx = get_idx(client)
    try:
        return root.get_child([
            ua.QualifiedName("Objects", 0),
            ua.QualifiedName("FMU", idx),
            ua.QualifiedName(name, idx)
        ])
    except Exception:
        return None

def read_opc_real(client, name, default=None):
    node = get_node(client, name)
    if node is None:
        return default
    try:
        return float(node.get_value())
    except Exception:
        return default

def write_opc_real(client, name, value):
    node = get_node(client, name)
    if node is None:
        return
    try:
        node.set_value(ua.Variant(float(value), ua.VariantType.Double))
    except Exception:
        pass

# ====== PLOTS ======
def plot_results(df, input_names, output_names, pdf_path):
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    with plt.rc_context({'figure.max_open_warning': 0}):
        fig_in, axs_in = plt.subplots(max(1, len(input_names)), 1, figsize=(10, 2 * max(1, len(input_names))), sharex=True)
        if len(input_names) == 1:
            axs_in = [axs_in]
        for i, n in enumerate(input_names):
            axs_in[i].plot(df["time"], df[n], label=n)
            axs_in[i].set_ylabel(n); axs_in[i].grid(True)
        axs_in[-1].set_xlabel("Time [s]")
        fig_in.suptitle("Input Variables")
        fig_in.tight_layout(rect=[0, 0.03, 1, 0.95])

        fig_out, axs_out = plt.subplots(max(1, len(output_names)), 1, figsize=(10, 2 * max(1, len(output_names))), sharex=True)
        if len(output_names) == 1:
            axs_out = [axs_out]
        for i, n in enumerate(output_names):
            axs_out[i].plot(df["time"], df[n], label=n)
            axs_out[i].set_ylabel(n); axs_out[i].grid(True)
        axs_out[-1].set_xlabel("Time [s]")
        fig_out.suptitle("Output Variables")
        fig_out.tight_layout(rect=[0, 0.03, 1, 0.95])

        with PdfPages(pdf_path) as pdf:
            pdf.savefig(fig_in)
            pdf.savefig(fig_out)

# ====== MAIN ======
def simulate_fmu():
    logger.info(f"FMU: {FMU_PATH}")
    # --- OPC connect (no es crítico: si falla, simula sin OPC)
    opc = None
    try:
        opc = OPCClient(OPCUA_ENDPOINT)
        opc.connect()
        logger.info(f"OPC UA conectado a {OPCUA_ENDPOINT}")
    except Exception as e:
        logger.warning(f"No se pudo conectar a OPC UA ({e}). Continuando sin OPC...")

    model_description = read_model_description(FMU_PATH)
    unzipdir = extract(FMU_PATH)
    logger.info(f"FMU extraída en: {unzipdir}")

    vrs = {v.name: v.valueReference for v in model_description.modelVariables}

    input_names  = [v.name for v in model_description.modelVariables if v.causality == "input" and v.type == "Real"]
    output_names = DEFAULT_OUTPUTS  # ajusta si quieres detectar outputs automáticamente

    results = []
    fmu = None
    try:
        fmu = FMU2Slave(
            guid=model_description.guid,
            unzipDirectory=unzipdir,
            modelIdentifier=model_description.coSimulation.modelIdentifier,
            instanceName='instance1'
        )
        fmu.instantiate()
        fmu.setupExperiment(startTime=START_TIME)
        fmu.enterInitializationMode()

        # Inicializa inputs con OPC si está disponible
        for name in input_names:
            if name in vrs:
                val = read_opc_real(opc, name, default=None) if opc else None
                if val is not None:
                    fmu.setReal([vrs[name]], [float(val)])

        fmu.exitInitializationMode()
        logger.info("Simulación iniciada")

        sim_time = START_TIME
        while sim_time <= STOP_TIME:
            # Lee inputs actuales (OPC) y se los pasa a la FMU
            for name in input_names:
                if name in vrs and opc:
                    val = read_opc_real(opc, name, default=None)
                    if val is not None:
                        fmu.setReal([vrs[name]], [float(val)])

            # Captura inputs antes del paso
            input_vals = fmu.getReal([vrs[n] for n in input_names]) if input_names else []

            # Avanza
            fmu.doStep(currentCommunicationPoint=sim_time, communicationStepSize=STEP_SIZE)

            # Lee outputs
            out_vals = []
            for n in output_names:
                if n in vrs:
                    out_vals.append(fmu.getReal([vrs[n]])[0])
                else:
                    out_vals.append(float('nan'))

            # Publica outputs en OPC
            if opc:
                for n, val in zip(output_names, out_vals):
                    write_opc_real(opc, n, val)

            # Guarda fila
            row = {"time": sim_time}
            row.update(dict(zip(input_names, input_vals)))
            row.update(dict(zip(output_names, out_vals)))
            results.append(row)

            sim_time += STEP_SIZE
            time.sleep(0)  # sin “tiempo real”; pon time.sleep(STEP_SIZE) si quieres ritmo real

        fmu.terminate(); fmu.freeInstance()
        logger.info("Simulación completada")

        df = pd.DataFrame(results)
        df.to_csv(OUTPUT_CSV, index=False)
        print(f"✅ Resultados CSV: {OUTPUT_CSV}")

        plot_results(df, input_names, output_names, PLOT_PDF)
        print(f"📊 PDF con gráficos: {PLOT_PDF}")

    finally:
        shutil.rmtree(unzipdir, ignore_errors=True)
        if opc:
            try: opc.disconnect()
            except Exception: pass
        logger.info("Limpieza de temporales finalizada.")

if __name__ == "__main__":
    simulate_fmu()
