# simple-pid: a stateful class from PyPI

The `PID` class from [simple-pid](https://github.com/m-lundberg/simple-pid), used exactly as published on PyPI:

```python
pid = PID(Kp=2.0, Ki=0.5, Kd=0.0, setpoint=1.0)
output = pid(measurement, dt=0.1)   # once per step
```

- **Source:** `simple-pid==2.0.1` from PyPI. MIT License, © 2018-2024 Martin Lundberg. There is no copy of the code in this repository; it must be installed in the environment fmugen runs in (`uv sync` does this here).
- **What the config shows:**
  - The entry is an installed module (`simple_pid:PID`), listed in `requirements`.
  - Constructor arguments are parameters. `Kp`, `Ki`, `Kd`, `setpoint` and `auto_mode` are `tunable`, because `__call__` reads those attributes every step; changing one during the simulation writes it onto the PID object.
  - `[time] dt = "step_size"` passes the FMU step size as `dt`, instead of simple-pid measuring wall-clock time.
  - Non-FMI arguments go in `[model.constants]`: `output_limits` is a tuple, and `sample_time = None` makes the PID compute on every step.
  - The FMU variable `measurement` is bound to the argument `input_`. The output is the return value.
  - The PID's private integral term `_integral` is exposed as a local, for plotting.
  - The PID object holds all the controller state, so saving and restoring FMU state rolls it back.

Build, validate and simulate:

```bash
fmugen build examples/simple_pid -o out/simple_pid.fmu
```

```bash
fmpy validate out/simple_pid.fmu
```

```bash
fmpy simulate out/simple_pid.fmu --output-file out/simple_pid.csv
```

Expected: the measurement stays 0 while the setpoint is 1, so `output = Kp·1 + Ki·1·t = 2 + 0.5·t`. That is 2.05 after the first step and 7.0 at t = 10 s.

Try a different tuning:

```bash
fmpy simulate out/simple_pid.fmu --start-values Kp 4 Ki 1 --output-file out/simple_pid_tuned.csv
```
