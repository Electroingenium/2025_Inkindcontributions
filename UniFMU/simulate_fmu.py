import numpy as np
import pandas as pd
from fmpy import simulate_fmu, read_model_description,dump
import os

# === Configuration ===
fmu_path = 'UniFMU\ORIGINAL_generated_autov2.fmu'  # Path to your FMU
start_time = 0.0
stop_time = 10.0
step_size = 1.0
dump(fmu_path)

# === Load model description (optional, useful for variable names) ===
model_description = read_model_description(fmu_path)

# === Input preparation ===
# Extract input variable names from the model (you can hardcode if preferred)
input_names = [v.name for v in model_description.modelVariables if v.causality == 'input']

n_steps = int((stop_time - start_time) / step_size) + 1
time = np.linspace(start_time, stop_time, n_steps)

# Create constant input values (1.0 for all inputs, can be customized)
input_values = np.full((n_steps, len(input_names)), 1.0)
input_data = np.column_stack([time, input_values])

# Create DataFrame with input values
df_inputs = pd.DataFrame(input_data, columns=['time'] + input_names)

# === Run simulation ===
result = simulate_fmu(
    filename=fmu_path,
    start_time=start_time,
    stop_time=stop_time,
    step_size=step_size,
    input=df_inputs
)

# === Save results ===
results_file = "simulation_results.csv"
pd.DataFrame(result).to_csv(results_file, index=False)

print(f"✅ Simulation complete. Results saved to: {results_file}")
