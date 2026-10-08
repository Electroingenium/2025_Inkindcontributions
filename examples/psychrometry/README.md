# Psychrometry: a plain function

A simplified mass and energy balance of an air-based drying process. It is a stateless function that takes 18 temperatures, humidities and flow rates and returns a dict:

```python
def compute_balances_simplified(regen_target_temp, ..., vfr_13):
    ...
    return {"mass_balance": ..., "energy_balance": ..., "mdot_air_in": ..., ...}
```

- **Source:** the original model by Lucia Royo-Pascual, Ph.D. (EIUM).
- **What the config shows:**
  - every argument is an input, with start values and units
  - each output reads the returned dict key with its own name (the default for functions)
  - the function is also called on initialization, so outputs are valid at time 0

Build, validate and simulate:

```bash
fmugen build examples/psychrometry -o out/psychrometry.fmu
```

```bash
fmpy validate out/psychrometry.fmu
```

```bash
fmpy simulate out/psychrometry.fmu --stop-time 5 --start-values temp_1 30 --output-file out/psychrometry.csv
```

Expected: constant outputs, with `Q_in` = 2.4 kg/s × 1010 J/(kg·K) × 30 = 72720 W.
