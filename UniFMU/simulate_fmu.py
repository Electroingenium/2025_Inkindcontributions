import numpy as np
import pandas as pd
from fmpy import simulate_fmu
from fmpy import read_model_description
import os

# Ruta a la FMU generada
fmu_path = 'python_adder_model_eium_generated.fmu'

# Leer descripción del modelo para ver nombres de variables si es necesario
model_description = read_model_description(fmu_path)

# Crear datos de entrada de ejemplo (simulación de 0 a 10 con paso 1s)
start_time = 0.0
stop_time = 10.0
step_size = 1.0
n_steps = int((stop_time - start_time) / step_size) + 1
time = np.linspace(start_time, stop_time, n_steps)

# Suponer entrada constante (puedes personalizar estos valores)
input_values = np.full((n_steps, 18), 1.0)  # Todos los inputs a 1.0
input_data = np.column_stack([time, input_values])

# Crear nombres de inputs
input_names = [f'u{i}' for i in range(18)]

# Crear DataFrame para entrada
df_inputs = pd.DataFrame(input_data, columns=['time'] + input_names)

# Simular
result = simulate_fmu(fmu_path, start_time=start_time, stop_time=stop_time, step_size=step_size, input=df_inputs)

# Mostrar salidas clave
output_names = [
    "mass_balance", "energy_balance", "mdot_air_in",
    "mdot_air_out", "Q_in", "Q_out"
]

print("\n📊 Final values of outputs:")
for name in output_names:
    if name in result:
        print(f"{name}: {result[name][-1]}")
    else:
        print(f"{name}: not found in result")

# Exportar resultados a CSV
pd.DataFrame(result).to_csv("simulation_results.csv", index=False)
print("\n✅ Simulation complete. Results saved to simulation_results.csv")