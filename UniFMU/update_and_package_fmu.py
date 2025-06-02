import os
import pickle
import zipfile
from pathlib import Path

# === FMU resource path ===
FMU_DIR = Path("ORIGINAL.fmu")
RESOURCE_DIR = FMU_DIR / "resources"
FMU_DIR.mkdir(parents=True, exist_ok=True)
RESOURCE_DIR.mkdir(parents=True, exist_ok=True)

# === Define I/O variable names ===
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
assignment_block = "\n        ".join([f"self.{name} = {value}" for name, value in zip(inputs, initial_values)] + [f"self.{name} = 0.0" for name in outputs])
result_assignments = "\n        ".join([f"self.{name} = results[{i}]" for i, name in enumerate(outputs)])

model_code = f"""from fmi2 import Fmi2FMU, Fmi2Status
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
    def __init__(self, reference_to_attr=None) -> None:
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
        input_values = [{", ".join(f"self.{name}" for name in inputs)}]
        results = compute_balances_simplified(input_values)
        {result_assignments}

    def do_step(self, current_time, step_size, no_step_prior):
        self._update_outputs()
        return Fmi2Status.ok
"""

(RESOURCE_DIR / "model.py").write_text(model_code.strip())

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

for i, (name, value) in enumerate(zip(inputs, initial_values)):
    xml += f'''    <ScalarVariable name="{name}" valueReference="{i}" causality="input" variability="continuous">
      <Real start="{value}" />
    </ScalarVariable>\n'''

for i, name in enumerate(outputs, start=len(inputs)):
    xml += f'''    <ScalarVariable name="{name}" valueReference="{i}" causality="output" variability="continuous" initial="calculated">
      <Real />
    </ScalarVariable>\n'''

xml += '''  </ModelVariables>
  <ModelStructure>
    <Outputs>
'''
for i in range(len(inputs), len(inputs) + len(outputs)):
    xml += f'      <Unknown index="{i+1}" />\n'

xml += '''    </Outputs>
    <InitialUnknowns>
'''
for i in range(len(inputs), len(inputs) + len(outputs)):
    xml += f'      <Unknown index="{i+1}" />\n'

xml += '''    </InitialUnknowns>
  </ModelStructure>
</fmiModelDescription>
'''

(FMU_DIR / "modelDescription.xml").write_text(xml.strip())

# === Zip and rename as .fmu ===
zip_path = Path("ORIGINAL_generated_auto.zip")
fmu_final_path = Path("ORIGINAL_generated_auto.fmu")

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for file in FMU_DIR.rglob("*"):
        zipf.write(file, arcname=file.relative_to(FMU_DIR))

zip_path.rename(fmu_final_path)

print(f"✅ FMU generated: {fmu_final_path}")
