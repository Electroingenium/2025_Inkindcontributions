# RC building zone: a multi-file package with fed-back state

The `Zone` class from [RC_BuildingSimulator](https://github.com/architecture-building-systems/RC_BuildingSimulator): an ISO 13790 5R1C resistance-capacitance thermal model of a building zone, with heating and cooling systems.

```python
zone = Zone(floor_area=35.0, ...)
zone.solve_energy(internal_gains, solar_gains, t_out, t_m_prev)   # once per hour
zone.t_air, zone.heating_demand, zone.t_m_next, ...                # results are attributes
```

**Source:** `rc_simulator/` holds `__init__.py`, `building_physics.py`, `supply_system.py` and `emission_system.py`. They were copied unmodified from commit [`97c1cdd`](https://github.com/architecture-building-systems/RC_BuildingSimulator/tree/97c1cdd72679de891e2a8526a991dc59234873bb/rc_simulator), with the project's LICENSE (`rc_simulator/LICENSE`): MIT License (amended), © 2016 Architecture and Building Systems, ETH Zürich. Research use requires a reference back to the department of Architecture and Building Systems of ETH Zürich. The other upstream files (radiation, examples, tests) aren't needed by `Zone` and were left out.

What the config shows:

- **Several files with flat imports.** `building_physics.py` does `import supply_system`, so `sources = ["rc_simulator"]` copies the directory and its folder goes on `sys.path`.
- **Results stored as attributes.** `solve_energy` returns nothing, so outputs and locals read attributes of the `Zone` object.
- **Fed-back state.** The method needs the previous step's thermal-mass temperature (`t_m_prev`) and stores the next one in `t_m_next`. `[states] t_m_prev = { next = "attr:t_m_next" }` closes that loop.
- **Fixed step.** The model hard-codes a one-hour step, so `fixed_step = true` with `step_size = 3600`. The FMU declares `canHandleVariableCommunicationStepSize="false"` and rejects other step sizes.
- **Calculated parameters.** `c_m`, `h_tr_em` and `h_tr_w` are derived in `__init__`; they are exposed as `calculatedParameter`s.
- **Tunable set points.** `solve_energy` reads `t_set_heating` and `t_set_cooling` every step, so they are `tunable`.
- **Constants.** `heating_supply_system` and `cooling_supply_system` are classes, passed with `{ ref = "supply_system:HeatPumpAir" }`.

`weather.csv` drives the inputs: two cold winter days at hourly resolution, with outdoor temperature, internal gains and solar gains.

Build, validate and simulate:

```bash
fmugen build examples/rc_building -o out/rc_building.fmu
```

```bash
fmpy validate out/rc_building.fmu
```

```bash
fmpy simulate out/rc_building.fmu --input-file examples/rc_building/weather.csv --output-interval 3600 --output-file out/rc_building.csv
```

Expected: heating keeps `t_air` at the 20 °C set point. `heating_demand` is about 0.8–1 kW at night, and drops to 0 in the afternoon when solar and internal gains are enough, which lets `t_air` drift slightly above 20 °C.
