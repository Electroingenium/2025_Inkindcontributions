# Kalman filter: FMI 3 arrays, structural parameters and a triggered clock

`KalmanFilter` from [FilterPy](https://github.com/rlabbe/filterpy), used exactly as published, tracks an object's position and velocity from noisy position measurements:

```python
kf = KalmanFilter(dim_x=2, dim_z=1)
kf.F, kf.H, kf.Q, kf.R = ...    # matrices
kf.predict()                    # every time step
kf.update(z)                    # whenever a measurement arrives
kf.x, kf.P                      # estimate and covariance
```

- **Source:** `filterpy==1.4.5` from PyPI. MIT License, © 2015 Roger R. Labbe Jr. There is no copy in this repository. FilterPy needs numpy and scipy, so it isn't vendored here; install it in the runtime Python. In this project, `uv sync` installs it as a dev dependency.
- **What the config shows:**
  - **Structural parameters:** `dim_x` and `dim_z` are the constructor's sizes, as `UInt64` structural parameters. An importer can change them in configuration mode.
  - **Arrays:** `F`, `H`, `Q` and `R` are parameters with `dimensions = ["dim_x", "dim_x"]` and so on. They are passed as numpy arrays (`numpy = true`) and written onto the filter (`to = "attr:F"`). The outputs `x` (2 values) and `P` (2×2) are read from the filter's attributes.
  - **Step method:** `call = "predict"`, the time update on every step. `fixed_step = true`, because `F` assumes 0.1 s.
  - **Triggered input clock:** `[clocks.measurement] call = "update"`. When the importer ticks it, the clocked array input `z` is passed to `kf.update(z)`, and the clocked output `y` (innovation) is read afterwards.

Build, validate, and run it with the small importer in `run.py`. It steps every 0.1 s and ticks `measurement` every 0.3 s with a noisy position:

```bash
uv run fmugen build examples/kalman -o out/kalman.fmu --python
```

```bash
uv run fmpy validate out/kalman.fmu
```

```bash
uv run python examples/kalman/run.py out/kalman.fmu
```

Expected: the estimate starts at 0 and jumps towards each measurement. It converges on the true motion: about 4.7 m and 0.95 m/s at t = 5 s, against a true 5 m and 1 m/s.
