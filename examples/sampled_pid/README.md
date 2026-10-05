# Sampled PID: an FMI 3 periodic clock

The same `PID` class from [simple-pid](https://github.com/m-lundberg/simple-pid) as [`examples/simple_pid`](../simple_pid), unchanged. This time it is a **sampled-data controller**: it runs when the FMI 3 clock `sample` ticks, every 0.1 s, independently of the importer's communication step.

- **Source:** `simple-pid==2.0.1` from PyPI. MIT License, © 2018-2024 Martin Lundberg. It must be installed in the environment fmugen runs in.
- **What the config shows:**
  - `fmi_version = 3`, because clocks are FMI 3.
  - `call = false`: nothing runs on `doStep`; only the clock runs code.
  - A **periodic input clock**: `[clocks.sample] interval = 0.1` with `call = "__call__"`. The importer ticks it every 0.1 s, and on each tick the FMU calls `pid(measurement, dt)`.
  - **Clocked variables:** `measurement` (`clocks = ["sample"]`) is passed to the tick, and `output` is read from its return value. Both hold their value between ticks.
  - `[time] dt = "step_size"`: in a clock call this is the time since the clock last ticked (0.1 s here), so the PID integrates correctly whatever the importer's step size is.

Build, validate, and run it with the small importer in `run.py`. `fmpy simulate` doesn't tick input clocks, so `run.py` steps every 0.05 s, ticks the clock every 0.1 s, and closes the loop with a first-order plant:

```bash
fmugen build examples/sampled_pid -o out/sampled_pid.fmu
```

```bash
fmpy validate out/sampled_pid.fmu
```

```bash
uv run python examples/sampled_pid/run.py out/sampled_pid.fmu
```

Expected: the PID output changes only every second row (each tick) and is held in between. The measurement rises from 0 towards the set point 1 (about 0.78 at t = 2 s).
