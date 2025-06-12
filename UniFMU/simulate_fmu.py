import time
import shutil
import logging
import pandas as pd
from fmpy import read_model_description, extract
from fmpy.fmi2 import FMU2Slave
from pathlib import Path
import matplotlib.pyplot as plt

# === CONFIGURATION ===
FMU_PATH = Path("FMUs/ORIGINAL_modified_auto.fmu").resolve()
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

OUTPUT_CSV = RESULTS_DIR / "simulation_inputs_outputs.csv"
PLOT_PDF = RESULTS_DIR / "simulation_plots.pdf"
START_TIME = 0.0
STOP_TIME = 10.0
STEP_SIZE = 1.0

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def simulate_fmu():
    model_description = read_model_description(FMU_PATH)
    unzipdir = extract(FMU_PATH)
    logger.info(f"FMU extracted to: {unzipdir}")

    vrs = {v.name: v.valueReference for v in model_description.modelVariables}

    input_names = [v.name for v in model_description.modelVariables if v.causality == "input" and v.type == "Real"]
    output_names = ["mass_balance", "energy_balance", "mdot_air_in", "mdot_air_out", "Q_in", "Q_out"]
    results = []

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
        fmu.exitInitializationMode()

        logger.info("Simulation started")
        sim_time = START_TIME
        while sim_time <= STOP_TIME:
            input_vals = fmu.getReal([vrs[name] for name in input_names])
            fmu.doStep(currentCommunicationPoint=sim_time, communicationStepSize=STEP_SIZE)
            output_vals = fmu.getReal([vrs[name] for name in output_names])

            row = {"time": sim_time}
            row.update(dict(zip(input_names, input_vals)))
            row.update(dict(zip(output_names, output_vals)))
            results.append(row)

            sim_time += STEP_SIZE

        fmu.terminate()
        fmu.freeInstance()
        logger.info("Simulation completed.")

        df = pd.DataFrame(results)
        df.to_csv(OUTPUT_CSV, index=False)
        print(f"✅ Simulation complete. Results saved to: {OUTPUT_CSV}")

        plot_results(df, input_names, output_names)

    finally:
        shutil.rmtree(unzipdir, ignore_errors=True)
        logger.info("Temporary files removed.")

def plot_results(df, input_names, output_names):
    with plt.rc_context({'figure.max_open_warning': 0}):
        fig_inputs, axs_in = plt.subplots(len(input_names), 1, figsize=(10, 2 * len(input_names)), sharex=True)
        fig_outputs, axs_out = plt.subplots(len(output_names), 1, figsize=(10, 2 * len(output_names)), sharex=True)

        for i, name in enumerate(input_names):
            axs_in[i].plot(df["time"], df[name], label=name)
            axs_in[i].set_ylabel(name)
            axs_in[i].grid(True)

        axs_in[-1].set_xlabel("Time [s]")
        fig_inputs.suptitle("Input Variables")
        fig_inputs.tight_layout(rect=[0, 0.03, 1, 0.95])

        for i, name in enumerate(output_names):
            axs_out[i].plot(df["time"], df[name], label=name, color="tab:blue")
            axs_out[i].set_ylabel(name)
            axs_out[i].grid(True)

        axs_out[-1].set_xlabel("Time [s]")
        fig_outputs.suptitle("Output Variables")
        fig_outputs.tight_layout(rect=[0, 0.03, 1, 0.95])

        from matplotlib.backends.backend_pdf import PdfPages
        with PdfPages(PLOT_PDF) as pdf:
            pdf.savefig(fig_inputs)
            pdf.savefig(fig_outputs)

        print(f"📊 Plots saved to: {PLOT_PDF}")

if __name__ == "__main__":
    simulate_fmu()
