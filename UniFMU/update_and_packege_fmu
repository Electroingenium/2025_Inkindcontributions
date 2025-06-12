import os
import sys
import shutil
import pickle
import zipfile
from pathlib import Path

# === Initial configuration ===
SOURCE_FMU = Path("FMUs/ORIGINAL.fmu")              # Original FMU
MODIFIED_DIR = Path("FMUs/ORIGINAL_modified.fmu")   # Modified FMU folder
RESOURCE_DIR = MODIFIED_DIR / "resources"

# === Copy original folder ===
if MODIFIED_DIR.exists():
    shutil.rmtree(MODIFIED_DIR)
shutil.copytree(SOURCE_FMU, MODIFIED_DIR)
print(f"📁 Copy of {SOURCE_FMU} created at: {MODIFIED_DIR.resolve()}")

# === Input and output variables ===
inputs = [
    "regen_target_temp", "regen_vfr_setpoint", "regen_heater_power",
    "temp_1", "RH_1", "vfr_1",
    "temp_3", "RH_3", "vfr_5",
    "temp_6", "RH_6",
    "vfr_8", "temp_9", "RH_9",
    "temp_10", "RH_10", "temp_11", "vfr_13"
]
initial_values = [
    60.0, 0.1, 0.0,
    25.0, 0.5, 0.1,
    25.0, 0.5, 0.1,
    25.0, 0.5,
    0.1, 25.0, 0.5,
    25.0, 0.5, 25.0, 0.1
]
outputs = ["mass_balance", "energy_balance", "mdot_air_in", "mdot_air_out", "Q_in", "Q_out"]

# === Generate model.py ===
assignment_block = "\n        ".join([f"self.{n} = {v}" for n, v in zip(inputs, initial_values)] + [f"self.{n} = 0.0" for n in outputs])
result_block = "\n        ".join([f"self.{n} = results[{i}]" for i, n in enumerate(outputs)])

model_py = f"""from fmi2 import Fmi2FMU, Fmi2Status
import pickle

def compute_balances_simplified(inputs):
    rho_air = 1.2
    Cp_air = 1010
    vfr_5 = inputs[8]
    vfr_8 = inputs[11]
    vfr_13 = inputs[17]
    temp_1 = inputs[3]
    temp_11 = inputs[16]
    mdot_air_5 = vfr_5 * rho_air
    mdot_air_8 = vfr_8 * rho_air
    mdot_air_13 = vfr_13 * rho_air
    mdot_air_in = mdot_air_5 + mdot_air_8
    mdot_air_out = mdot_air_13
    mass_balance = mdot_air_in - mdot_air_out
    Q_in = mdot_air_in * Cp_air * temp_1
    Q_out = mdot_air_out * Cp_air * temp_11
    energy_balance = Q_in - Q_out
    return [mass_balance, energy_balance, mdot_air_in, mdot_air_out, Q_in, Q_out]

class Model(Fmi2FMU):
    def __init__(self, reference_to_attr=None):
        super().__init__(reference_to_attr)
        {assignment_block}
        self._update_outputs()

    def serialize(self):
        state = tuple([getattr(self, name) for name in {inputs + outputs}])
        return Fmi2Status.ok, pickle.dumps(state)

    def deserialize(self, data):
        values = pickle.loads(data)
        for name, val in zip({inputs + outputs}, values):
            setattr(self, name, val)
        self._update_outputs()
        return Fmi2Status.ok

    def _update_outputs(self):
        input_values = [{", ".join(f"self.{n}" for n in inputs)}]
        results = compute_balances_simplified(input_values)
        {result_block}

    def do_step(self, current_time, step_size, no_step_prior):
        self._update_outputs()
        return Fmi2Status.ok
"""

(RESOURCE_DIR / "model.py").write_text(model_py.strip())
print(f"✅ model.py updated at: {RESOURCE_DIR / 'model.py'}")

# === Generate modelDescription.xml ===
xml = '''<?xml version='1.0' encoding='utf-8'?>
<fmiModelDescription fmiVersion="2.0" modelName="unifmu" guid="77236337-210e-4e9c-8f2c-c1a0677db21b" author="L. Royo-Pascual" generationDateAndTime="2020-10-23T19:51:25Z" variableNamingConvention="flat" generationTool="unifmu">
  <CoSimulation modelIdentifier="unifmu" needsExecutionTool="true" canNotUseMemoryManagementFunctions="false" canHandleVariableCommunicationStepSize="true" canGetAndSetFMUstate="true" canSerializeFMUstate="true" />
  <LogCategories>
    <Category name="logStatusWarning" />
    <Category name="logStatusDiscard" />
    <Category name="logStatusError" />
    <Category name="logStatusFatal" />
    <Category name="logStatusPending" />
    <Category name="logAll" />
  </LogCategories>
  <ModelVariables>
'''

for i, (n, v) in enumerate(zip(inputs, initial_values)):
    xml += f'''    <ScalarVariable name="{n}" valueReference="{i}" causality="input" variability="continuous">
      <Real start="{v}" />
    </ScalarVariable>\n'''
for i, n in enumerate(outputs, start=len(inputs)):
    xml += f'''    <ScalarVariable name="{n}" valueReference="{i}" causality="output" variability="continuous" initial="calculated">
      <Real />
    </ScalarVariable>\n'''

xml += '''  </ModelVariables>
  <ModelStructure>
    <Outputs>\n'''
for i in range(len(inputs), len(inputs) + len(outputs)):
    xml += f'      <Unknown index="{i+1}" />\n'
xml += '''    </Outputs>
    <InitialUnknowns>\n'''
for i in range(len(inputs), len(inputs) + len(outputs)):
    xml += f'      <Unknown index="{i+1}" />\n'
xml += '''    </InitialUnknowns>
  </ModelStructure>
</fmiModelDescription>
'''

(MODIFIED_DIR / "modelDescription.xml").write_text(xml.strip())
print(f"✅ modelDescription.xml updated at: {MODIFIED_DIR / 'modelDescription.xml'}")

# === Dynamic launch.toml ===
python_exec = sys.executable.replace("\\", "/")
launch_toml = f"""backend = "grpc"

[grpc]
linux = ["python3", "backend_grpc.py"]
macos = ["python3", "backend_grpc.py"]
windows = ["{python_exec}", "backend_grpc.py"]

[zmq]
linux = ["python3", "backend_schemaless_rpc.py"]
macos = ["python3", "backend_schemaless_rpc.py"]
serialization_format = "Pickle"
windows = ["{python_exec}", "backend_schemaless_rpc.py"]
"""

(RESOURCE_DIR / "launch.toml").write_text(launch_toml.strip())
print(f"✅ launch.toml updated at: {RESOURCE_DIR / 'launch.toml'}")

# === Generate .fmu ===
zip_path = Path("FMUs/ORIGINAL_modified_auto.zip")
fmu_final_path = Path("FMUs/ORIGINAL_modified_auto.fmu")

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for file in MODIFIED_DIR.rglob("*"):
        zipf.write(file, arcname=file.relative_to(MODIFIED_DIR))

zip_path.rename(fmu_final_path)
print(f"✅ Final FMU generated at: {fmu_final_path.resolve()}")
