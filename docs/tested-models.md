# Tested models

fmugen has been tried on 131 published, unmodified Python models (three needed a file renamed or a script wrapped in a class, and one synthetic input data; see their notes): the examples in this repository, models from more than 100 libraries on PyPI, 6 neural networks and 13 models built on [GEKKO](https://github.com/BYU-PRISM/GEKKO). Each model is listed once, with its most recent result. A [second batch](#second-batch) of 99 models from other libraries (44 neural networks) was tested later the same way: 51 simulate with useful results, 40 compiled; 29 fail because the library has no model to point `init` at, 19 on fmugen problems found there.

- [How the models were tested](#how-the-models-were-tested)
- [Summary](#summary)
- [Repository examples](#repository-examples)
- [Python libraries](#python-libraries)
- [Neural networks](#neural-networks)
- [GEKKO models](#gekko-models)
- [Hand configs](#hand-configs)
- [Second batch](#second-batch)
- [Known problems](#known-problems)
- [Versions](#versions)
- [Reproducing a run](#reproducing-a-run)

---

## How the models were tested

Each model went through:

1. `fmugen init` (code only)
2. `fmugen init --probe`
3. `fmugen build --capture-output` on each config `init` wrote (and on the committed `fmugen.toml` for the repository examples), then `fmpy.simulate_fmu` for 3 s with 1 s outputs
4. `fmugen build --capture-output --compile pyinstaller` on the best config (the `--probe` one when it simulated), then the same simulation

**FMI 2 by default.** A model was run with FMI 3 only when no FMI 2 config simulated; the results below combine both.

Setup: fmugen at `6dfc18c` (2026-10-22), WSL 2 (Ubuntu), Python 3.13, `uv` venvs, FMPy 0.3.32, UniFMU 0.14, gekko 1.3.2 with its local solver. CGE ran on Windows 11. Every FMU was compared value by value with the model run directly ([report](match-testing-rerun/report.md)). The **Compiled** column: PyInstaller 6.22.3 in WSL 2 (Linux), each compiled FMU compared with the uncompiled one of the same config, value by value ([report](match-testing-compile-rest/report.md), [GEKKO and hand configs](match-testing-compile/report.md), [GEKKO retest](match-testing-compile/retest.md)). Sizes are of the Linux FMUs, except CGE's (Windows only). Compile in a venv with only what the model needs: extra packages make the FMU larger and the build slower.

Columns: **`init` / `init --probe`**: ✓ if the config of either one builds, simulates and outputs the model's results; otherwise how they failed (✗ no useful outputs: it runs, but only outputs parameters, settings or constants). **Hand config**: a config written by hand (for the examples, the repository's `fmugen.toml`), ✓ if it builds, simulates and outputs the model's results, with a link to it; — when the model needs none: ✓, ✗ no config (`init` stopped), ✗ build fails, ✗ simulate fails, or — (not run). **Compiled**: the best config compiled with PyInstaller, built and simulated. **Notes**: what was checked, or the error of each config that failed ("`init`:", "`init --probe`:").

---

## Summary

131 models: 118 from libraries, neural networks and the repository examples, and 13 built on GEKKO. FMI 2 and FMI 3 results are combined: a model counts as passing if it passes with either.

| | Models (131) |
|---|---|
| `init` writes a config | 125 |
| `init --probe` writes a config | 129 |
| **Simulates with useful results** (a config from `init` or `init --probe`) | **120** |
| …or with a hand-written config | **131** |
| Fails | 0 |
| **Compiled FMU simulates** | **131**: every model |

A config only counts as a success if the FMU simulates **and** gives the model's results. An FMU that runs but only outputs its own parameters, settings or constants counts as a failure.

How far each step gets:

| Config | Models | Success |
|---|---|---|
| `init` (code only) | 45 of 131 | 34 % |
| `init --probe` (or `init`, when it already works) | 120 of 131 | 92 % |
| `init --probe` + a hand-written config (for the examples, the repository's `fmugen.toml`) | 131 of 131 | 100 % |

The `init` config fails mostly on models that return arrays, tuples, strings or objects, which only `--probe` types correctly; the error message points to it. Of the 67 `init` configs of the first group that simulate, 23 only output parameters, settings or constants. GEKKO models keep their results in GEKKO variables, which only `--probe` finds. The hand configs add `PropsSI`, cantera, PyTCI and the kalman example ([Hand configs](#hand-configs)), pandapower, seirsplus, tellurium, the GEKKO model OpenHENS, sgp4, pymunk and pybamm ([configs](match-testing-rerun/configs/)).

Later, `init --probe` got 9 more without a hand config, each built, compiled with PyInstaller 6.22.3 and simulated in WSL 2; the compiled FMUs give exactly the values of the model called directly (157 values, t = 0–3; [probe-9](probe-9/CONCLUSION.md)): commpy and impedance (complex results split into real and imaginary parts), uncertainties and ambiance (a returned object's properties, one-element arrays read as their element), `fluids.units` ×2 and metpy (inputs retried as pint quantities, with units read from the errors) CFTOC (a `call:` start for the step method's copy of a shared argument is no longer refused) and river (when the probe finds no outputs, what the step changes becomes the outputs). seirsplus can't be done by `init`, an FMI limitation: its counts are arrays that grow by one element each step, and an FMI variable has a fixed size.

No model fails. The last 4 needed fmugen features, added after the main run and checked on these 4 models only (built, simulated, compiled and compared with a direct run; the other models weren't rerun with them):

| Model | What was missing | Feature |
|---|---|---|
| pymunk | `Space.bodies` is a `dict_keys` view, which a path couldn't index | A number in a path picks an element of any iterable, where there's no such attribute ([config.md](config.md)) |
| pybamm | The voltage is `solution["Voltage [V]"]` on an object that isn't a mapping | A path part is tried as a key on objects that take keys, where there's no such attribute |
| nashpy | `support_enumeration` returns a generator | Generator results are read into a tuple; `init --probe` splits nested tuples into `y0_0`, `y0_1` |
| pyet | Its inputs must be pandas Series with a date index | `convert = "series"` with an `epoch`, which `init --probe` writes when plain numbers and arrays fail |

**FMU vs direct run** ([report](match-testing-rerun/report.md)): every model was built into FMUs (`init --probe`, plain `init`, and the repository or hand configs; no `--compile`) and compared, output by output and step by step, with the model called directly in plain Python without fmugen. 130 of 134 match (236,621 values; largest relative difference 1.3 × 10⁻¹⁶, otherwise identical), counting psychrolib with numba and the two FMI 3 repository configs as separate entries. Models random by design were compared seeded. The other 4 are nashpy (no outputs to compare), pyet (the FMU fails), sgp4 (no config) and PyTCI's hand config, which differs from a per-step loop only at t = 0 ([PyTCI](#pytci)).

Checked later, after the features above: sgp4's hand config, pymunk, pybamm, nashpy and pyet all match the direct run with no difference, and so do their compiled FMUs. The `init --probe` configs of the 9 models added later (CFTOC, commpy, impedance, uncertainties, ambiance, `fluids.units` ×2, metpy, river) match it too, compiled and with no difference: 157 values over t = 0–3 ([probe-9](probe-9/CONCLUSION.md)).

CGE counts as a success after renaming its `model.py`, NHES with synthetic input data, OpenHENS with a hand-added output and the COIN-OR couenne solver.

---

## Repository examples

| Model | `init` / `init --probe` | Hand config (the repository's `fmugen.toml`) | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| [examples/psychrometry](../examples/psychrometry) (`compute_balances_simplified`) | ✓ | ✓ | ✓ (`init --probe` config, 108.7 MB) |  |
| [examples/simple_pid](../examples/simple_pid) (`simple_pid:PID`) | ✓ | ✓ | ✓ (`init --probe` config, 111.0 MB) |  |
| [examples/rc_building](../examples/rc_building) (`Zone`) | ✓ | ✓† | ✓ (`init --probe` config, 108.8 MB) | †The repo config fixes `step_size = 3600`, so the generic 1 s run is refused (correct); simulated at 3600 s steps. |
| [examples/kalman](../examples/kalman) (`filterpy.kalman:KalmanFilter`; repo config FMI 3: structural parameters, clock) | ✗ no useful outputs | ✓ | ✓ (repository config (FMI 3), 114.8 MB) | The `init` configs output only filter settings and likelihoods (`dim_x`, …, `alpha`, `likelihood`), not the state estimate. The repository config is driven by `examples/kalman/run.py`. |
| [examples/sampled_pid](../examples/sampled_pid) (`simple_pid:PID`; repo config: clocks) | ✓ | ✓ | ✓ (repository config (FMI 3), 111.1 MB) | The repo config is driven by `run.py` (clock ticked every 0.1 s, first-order plant). |

---

## Python libraries

Errors such as `y is an array of shape […], not a single value` in the `init` config are expected: `--probe` finds the shape.

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `ahrs.filters:Madgwick` | ✓ | — | ✓ (`init --probe` config, 50.3 MB) |  |
| `ahrs.filters:Mahony` | ✓ | — | ✓ (`init --probe` config, 50.3 MB) |  |
| `ambiance:Atmosphere` | ✓ | ✓ ([config](match-testing-rerun/configs/ambiance.toml)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` reads each one-element array property as its element (`return:temperature.0`, …): 281.65 K, 89 876 Pa at 1000 m. Before: The `init` configs output only the inputs: the results are properties returning 1-element arrays. The hand config reads element 0 of each (`return:temperature.0`, …). |
| `anastruct:SystemElements` | ✓ | — | ✓ (`init --probe` config, 88.5 MB) |  |
| `antropy:perm_entropy` | ✓ | — | ✓ (`init --probe` config, 164.9 MB) |  |
| `astral.sun:elevation` | ✓ | — | ✓ (`init --probe` config, 46.2 MB) |  |
| `astropy.cosmology:FlatLambdaCDM` | ✓ | — | ✓ (`init --probe` config, 65.2 MB) |  |
| `Bio.SeqUtils:gc_fraction` | ✓ | — | ✓ (`init --probe` config, 54.3 MB) |  |
| `blackscholes:BlackScholesCall` | ✓ | — | ✓ (`init --probe` config, 45.9 MB) |  |
| `cantera:Solution` | ✗ no useful outputs | ✓ ([config](#cantera)) | ✓ (hand config, 79.9 MB) | Outputs are only solver settings (`rtol`, `max_steps`): the results are Cython properties, and the gas state can't be set from inputs. |
| `chemicals.vapor_pressure:Antoine` | ✓ | — | ✓ (`init --probe` config, 126.5 MB) |  |
| `colour.temperature:CCT_to_xy_CIE_D` | ✓ | — | ✓ (`init --probe` config, 56.4 MB) |  |
| `commpy.modulation:QAMModem` | ✓ | ✓ ([config](match-testing-rerun/configs/commpy.toml)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` splits the complex symbols into `y_real` / `y_imag` (`return:real`, `return:imag`): (−1+1j, 1−1j), as `modulate` called directly. Before: `init`: only `m = 4`; the modulated symbols are complex, so they're left out. The hand config reads `.real` and `.imag` per symbol. |
| `control:StateSpace` | ✓ | — | ✓ (`init --probe` config, 124.6 MB) | Needs `--start x=[1.0, 0.0] --start u=[0.0]`. |
| `CoolProp.CoolProp:PropsSI` | ✗ build fails | ✓ ([config](models.md#positional-only-arguments)) | ✓ (hand config, 56.7 MB) | C extension with no signature: no variables inferred. |
| `cv2:KalmanFilter` | ✓ | — | ✓ (`init --probe` config, 163.5 MB) |  |
| `dysts:Lorenz` (`call = "rhs"`, `[model] integrate`) | — | ✓ | ✓ (hand config, 267.5 MB, both integrators) | Integrated by the FMU with `[model] integrate`: `"scipy:DOP853"` (FMI 3) or `"rk4"`, 50 substeps (FMI 2). |
| `electricpy:powerset` | ✓ | — | ✓ (`init --probe` config, 123.8 MB) |  |
| `erfa:gmst06` | ✓ | — | ✓ (`init --probe` config, 46.7 MB) |  |
| `filterpy.common:Q_discrete_white_noise` | ✓ | — | ✓ (`init --probe` config, 114.8 MB) |  |
| `filterpy.gh:GHFilter` | ✓ | — | ✓ (`init --probe` config, 114.8 MB) |  |
| `fluids.core:Reynolds` | ✓ | — | ✓ (`init --probe` config, 104.0 MB) |  |
| `fluids.friction:friction_factor` | ✓ | — | ✓ (`init --probe` config, 104.0 MB) |  |
| `fluids.units:head_from_P` | ✓ | ✓ ([config](#fluidsunits)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` retries with pint quantities and takes each input's unit from the error that names it (`convert = "pint"`, `unit = "Pa"`, …): 10.197 m. Before: TypeError: 100000.0 has no quantity |
| `fluids.units:Reynolds` | ✓ | ✓ ([config](#fluidsunits)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` retries with pint quantities, units from the errors: Re = 38 200.66. Before: TypeError: 1.0 has no quantity |
| `gsw:rho` | ✓ | — | ✓ (`init --probe` config, 48.3 MB) |  |
| `gymnasium.envs.classic_control.cartpole:CartPoleEnv` | ✓ | — | ✓ (seeded config, 104.0 MB) |  |
| `gymnasium.envs.classic_control.pendulum:PendulumEnv` | ✓ | — | ✓ (seeded config, 104.0 MB) |  |
| `haversine:haversine` | ✓ | — | ✓ (`init --probe` config, 44.8 MB) |  |
| `heartpy:process` | ✓ | — | ✓ (`init --probe` config, 119.6 MB) | **Needs `setuptools<81` installed by hand** (heartpy imports `pkg_resources` without declaring it), and its `data/data.csv` given by full path. |
| `highway_env.envs.highway_env:HighwayEnv` | ✓ | — | ✓ (seeded config, 104.2 MB) |  |
| `hplib.hplib:HeatPump` | ✓ | — | ✓ (`init --probe` config, 102.7 MB) |  |
| `ht.conv_internal:Nu_conv_internal` | ✓ | — | ✓ (`init --probe` config, 104.8 MB) |  |
| `ht.hx:effectiveness_from_NTU` | ✓ | — | ✓ (`init --probe` config, 104.8 MB) |  |
| `iapws.iapws97:_TSat_P` | ✓ | — | ✓ (`init --probe` config, 87.8 MB) |  |
| `iapws:IAPWS97` | ✓ | — | ✓ (`init --probe` config, 87.8 MB) |  |
| `impedance.models.circuits:Randles` | ✓ | ✓ ([config](match-testing-rerun/configs/impedance.toml)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` splits the complex prediction into `y_real` / `y_imag` at each frequency, identical to `predict` called directly. Needs pandas installed by hand (impedance imports it without declaring it). Before: `init`: outputs only echo `initial_guess`; the complex prediction is left out. The hand config reads `.real` and `.imag` at each frequency. |
| `joblib:load` | ✓ | — | ✓ (`init --probe` config, 112.8 MB) | **Compiled: needs `scikit-learn` added to `[model] requirements` by hand**: the model is unpickled, so nothing imports scikit-learn by name. Uncompiled, it needs nothing extra. |
| `librosa:hz_to_mel` | ✓ | — | ✓ (`init --probe` config, 167.7 MB) |  |
| `mendeleev:element` | ✓ | — | ✓ (`init --probe` config, 75.7 MB) |  |
| `mesa.examples:BoltzmannWealth` | ✓ | — | ✓ (seeded config, 105.2 MB) |  |
| `meteocalc:heat_index` | ✓ | — | ✓ (`init --probe` config, 44.8 MB) |  |
| `metpy.calc:dewpoint_from_relative_humidity` | ✓ | ✓ ([config](#metpy)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` retries with pint quantities; metpy names only the dimension, so the input gets its SI unit (`temperature` in K): set the unit your start is in (the hand config's `degC`). Before: ValueError: This function changed in version(s) ['1.0']--double check that the function is being called properly. |
| `nashpy:Game` | ✓ | — | ✓ (`init --probe` config, 94.9 MB) | `--call support_enumeration`, `--start A=… --start B=…` (a 2×2 game with one mixed equilibrium). The method returns a generator: its items are read into a tuple, and `--probe` writes `y0_0` and `y0_1`, the two players' strategies in the first equilibrium. Plain `init` fails (`float() argument must be … not 'generator'`). 0.0.43 has no `is_zero_sum`. |
| `neurokit2:ecg_simulate` | ✓ | — | ✓ (`init --probe` config, 150.4 MB) |  |
| `numdifftools:Derivative` | ✓ | — | ✓ (`init --probe` config, 90.8 MB) |  |
| `numpy_financial:pmt` | ✓ | — | ✓ (`init --probe` config, 46.0 MB) |  |
| `obspy.geodetics:gps2dist_azimuth` | ✓ | — | ✓ (`init --probe` config, 145.5 MB) |  |
| `openap:Thrust` | ✓ | — | ✓ (`init --probe` config, 106.7 MB) |  |
| `openturns:Normal` | ✓ | — | ✓ (`init --probe` config, 152.2 MB) |  |
| `pandapower:runpp` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/pandapower.toml), another entry) | ✓ (hand config, 124.1 MB) | `runpp(net)` returns None and writes its results onto `net`, which a function entry can't read back. The hand config uses `pandapower.contingency:run_contingency(net, nminus1_cases={})`, which runs the same `runpp` and returns its results (bus voltages, line and transformer loadings). |
| `pedon:Genuchten` | ✓ | — | ✓ (`init --probe` config, 129.0 MB) |  |
| `ppigrf:igrf` | ✓ | — | ✓ (`init --probe` config, 60.8 MB) |  |
| `psychrolib:GetHumRatioFromRelHum` | ✓ | — | ✓ (`init --probe` config, 44.8 MB; 110.2 MB with numba) | Also with numba installed, which makes psychrolib's functions ufuncs: `init` passes their arguments by position. |
| pvlib `get_total_irradiance` → `sapm_cell` → `pvwatts_dc` (**composite FMU**) | ✓ (each part) | — | ✓ (compiled on Windows) | The three parts made with `init --probe`. |
| `pvlib.atmosphere:alt2pres` | ✓ | — | ✓ (`init --probe` config, 132.8 MB) |  |
| `pvlib.iotools:read_tmy3` | ✓ | — | ✓ (`init --probe` config, 132.8 MB) |  |
| `pvlib.irradiance:aoi` | ✓ | — | ✓ (`init --probe` config, 132.8 MB) |  |
| `pvlib.pvsystem:pvwatts_dc` | ✓ | — | ✓ (`init --probe` config, 132.8 MB) |  |
| `pvlib.solarposition:get_solarposition` | ✓ | — | ✓ (`init --probe` config, 132.8 MB) |  |
| `pvlib.temperature:sapm_cell` | ✓ | — | ✓ (`init --probe` config, 132.8 MB) |  |
| `py_vollib.black_scholes:black_scholes` | ✓ | — | ✓ (`init --probe` config, 102.7 MB) |  |
| `pybamm:Simulation` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/pybamm.toml)) | ✓ (hand config, 265.2 MB) | `init`: outputs are only solver flags. The hand config reads the voltage as `return:Voltage [V].entries.-1`: `solution["Voltage [V]"]` on the `Solution` that `step()` returns. Without `init_call`: it would run one extra `step()` before t = 0. |
| `PyCO2SYS:sys` | ✓ | — | ✓ (`init --probe` config, 46.1 MB) |  |
| `pyet:pm_fao56` | ✓ | — | ✓ (`init --probe` config, 72.2 MB) | The inputs must be pandas Series with a date index (the day of the year comes from `rs.index`). With plain numbers the call fails (`'float' object has no attribute 'time'`), so `--probe` writes `convert = "series"` with an `epoch` for each number input. Checked over 5 days with varying `rs` and `tmean`. |
| `pyfluids:Fluid` | ✓ | — | ✓ (`init --probe` config, 56.7 MB) |  |
| `pygfunction.heat_transfer:finite_line_source` | ✓ | — | ✓ (`init --probe` config, 88.2 MB) |  |
| `pykalman:KalmanFilter` | ✓ | — | ✓ (`init --probe` config, 92.0 MB) |  |
| `pyloudnorm:Meter` | ✓ | — | ✓ (`init --probe` config, 91.2 MB) |  |
| `pymap3d:geodetic2enu` | ✓ | — | ✓ (`init --probe` config, 46.0 MB) |  |
| `pymsis:calculate` | ✓ | — | ✓ (`init --probe` config, 48.8 MB) |  |
| `pymunk:Space` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/pymunk.toml)) | ✓ (hand config, 48.7 MB) | `init`: outputs are only constant settings (`damping`, `collision_slop`, …). The hand config adds gravity and one body in `setup` and reads `attr:bodies.0.position.y`: `Space.bodies` is a `dict_keys` view, indexed by position. |
| `pyorbital.astronomy:sun_zenith_angle` | ✓ | — | ✓ (`init --probe` config, 107.7 MB) |  |
| `pyproj:Transformer` | ✓ | — | ✓ (`init --probe` config, 61.2 MB) |  |
| `pyquaternion:Quaternion` | ✓ | — | ✓ (`init --probe` config, 48.9 MB) | `--call rotate`, axis, angle, vector. Plain `init` fails: it passes axis and angle to the constructor by position. |
| `pyromat:get` | ✓ | — | ✓ (`init --probe` config, 47.0 MB) |  |
| `pysolar.solar:get_altitude` | ✓ | — | ✓ (`init --probe` config, 45.9 MB) |  |
| `PyTCI.models.propofol:Marsh` | ✗ no useful outputs | ✓ ([config](#pytci)) | ✓ (hand config, 87.6 MB) | Outputs only echo the parameters (`weight`, `time_seconds`): the state is in a nested function. |
| `pyteomics.mass:calculate_mass` | ✓ | — | ✓ (`init --probe` config, 51.6 MB) |  |
| `pythermalcomfort.models.jos3:JOS3` | ✓ | ✓ ([config](#jos3)) | ✓ (`init --probe` config, 153.8 MB) |  |
| `pythermalcomfort.models:pmv_ppd_iso` | ✓ | — | ✓ (`init --probe` config, 153.8 MB) |  |
| `pythermalcomfort.models:sports_heat_stress_risk` | ✓ | — | ✓ (`init --probe` config, 153.8 MB) |  |
| `pywt:dwt` | ✓ | — | ✓ (`init --probe` config, 53.3 MB) |  |
| `pyxirr:npv` | ✓ | — | ✓ (`init --probe` config, 45.3 MB) |  |
| `quantecon:LinearStateSpace` | ✓ | — | ✓ (`init --probe` config, 156.1 MB) |  |
| `QuantLib:blackFormula` | ✓ | — | ✓ (`init --probe` config, 78.8 MB) |  |
| `radioactivedecay:Inventory` | ✓ | — | ✓ (`init --probe` config, 135.5 MB) |  |
| `rainflow:count_cycles` | ✓ | — | ✓ (`init --probe` config, 48.8 MB) |  |
| `rdkit.Chem.Descriptors:MolWt` | ✓ | — | ✓ (`init --probe` config, 110.7 MB) |  |
| `river.linear_model:LinearRegression` | ✓ | ✓ ([config](match-testing-rerun/configs/river.toml)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` outputs the learned `intercept` (0.06 after the first step, as `learn_one` called directly): with no other outputs found, the attributes the step changes become outputs instead of locals. The weights (a dict) still need the hand config. Before: `init`: only hyperparameters (`l1`, `l2`, …). The hand config reads the learned weights (`attr:weights.a`, …) and the intercept. |
| `roboticstoolbox.models.DH:Panda` | ✓ | — | ✓ (`init --probe` config, 172.7 MB) |  |
| `scipy.signal:lfilter` | ✓ | — | ✓ (`init --probe` config, 98.3 MB) |  |
| `seirsplus.models:SEIRSModel` | ✗ not possible (FMI limitation) | ✓ ([config](match-testing-rerun/configs/seirsplus.toml)) | ✓ (hand config, 94.8 MB) | **Not possible with `init` (FMI limitation):** the counts (`numS`, `numI`, …) are arrays that grow by one element each step, and an FMI variable has a fixed size ([Limitations](#known-problems)). `init`: outputs only echo the parameters; the state arrays grow each step and are left out. The hand config reads the latest counts (`attr:numS.-1`, …) and sets `dt = 0.1`: with `dt` = the step size (1), `run_epoch` keeps only the start point and `t` never advances. |
| `sgp4.api:Satrec` | ✗ no config | ✓ ([config](match-testing-rerun/configs/sgp4.toml)) | ✓ (hand config, 44.9 MB) | `init`: C built-ins with no signature: `--start fr, jd, line1, line2: cannot tell which arguments these are …`. The hand config builds the satellite with `create = "twoline2rv"` from the two TLE lines and binds `sgp4(jd, fr)` by position (`to = "pos:N"`); outputs the error code, position (km) and velocity (km/s). Checked against `Satrec.sgp4` called directly: identical; the compiled FMU (PyInstaller 6.22.3, WSL 2) is identical to the uncompiled one. |
| `shapely:Point` | ✓ | — | ✓ (`init --probe` config, 50.3 MB) |  |
| `simglucose.patient.t1dpatient:T1DPatient` | ✓ | — | ✓ (`init --probe` config, 134.0 MB) |  |
| `simpy:Environment` | ✓ | — | ✓ (`init --probe` config, 44.8 MB) | `--call run`: `until` is bound to the step's end time. |
| `skfuzzy:interp_membership` | ✓ | — | ✓ (`init --probe` config, 94.5 MB) | **Needs scipy, packaging and networkx installed by hand**: scikit-fuzzy imports them without declaring them. |
| `skimage.color:rgb2hsv` | ✓ | — | ✓ (`init --probe` config, 127.1 MB) |  |
| `statsmodels.stats.proportion:proportion_confint` | ✓ | — | ✓ (`init --probe` config, 121.1 MB) |  |
| `tclab:TCLabModel` | ✓ | — | ✓ (`init` config, 44.9 MB) |  |
| `tellurium:loada` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/tellurium.toml)) | ✓ (hand config, 211.1 MB) | `init`: only `oneStep`'s return (the time reached). The hand config reads the species from the RoadRunner object (`attr:S1`, `attr:S2`). `currentTime` is a fixed input there; bind it with `[time] currentTime = "time"` to follow the simulation clock. On Linux it needs `LD_LIBRARY_PATH` set to Python's `lib` folder. |
| `thermo:Chemical` | ✓ | — | ✓ (`init --probe` config, 133.1 MB) |  |
| `thermofeel:calculate_heat_index_simplified` | ✓ | — | ✓ (`init --probe` config, 48.9 MB) |  |
| `timezonefinder:TimezoneFinder` | ✓ | — | ✓ (`init --probe` config, 80.6 MB) |  |
| `tmm:coh_tmm` | ✓ | — | ✓ (`init --probe` config, 49.1 MB) |  |
| `transforms3d.euler:euler2quat` | ✓ | — | ✓ (`init --probe` config, 47.3 MB) |  |
| `uncertainties:ufloat` | ✓ | ✓ ([config](match-testing-rerun/configs/uncertainties.toml)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | `init --probe` reads the returned object's properties; those named like an argument get the result's name: `y_nominal_value`, `y_std_dev`. Before: `init`: only `s`, the `ufloat` itself. The hand config reads `return:nominal_value` and `return:std_dev`. |
| `windpowerlib.wind_speed:logarithmic_profile` | ✓ | — | ✓ (`init --probe` config, 62.9 MB) |  |

---

## Neural networks

Each was installed as published (`pip install <package>`) into its own venv together with fmugen. Neural networks need `--probe`: their result sizes depend on the weights, and their code is mostly compiled or framework code. Weights from Hugging Face are downloaded on first use, unless the FMU is built with `--hf-weights` (automatic with `--vendor` / `--compile`). `--capture-output` is needed whenever a model prints while loading, which hangs UniFMU 0.14 otherwise. Compiled on Linux, their FMUs are 4.3–4.6 GB: torch from PyPI brings the NVIDIA CUDA libraries and triton (about 4 GB installed), and fmugen collects every dependency's binaries. Installing a CPU-only torch (`pip install torch --index-url https://download.pytorch.org/whl/cpu`) avoids them; Windows' torch has no CUDA, and compiled Windows FMUs were about 300 MB.

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `chronos:ChronosBoltPipeline` | ✓ | — | ✓ (`init --probe` config, 4.6 GB) |  |
| `silero_vad:load_silero_vad` | ✓ | — | ✓ (`init --probe` config, 4.5 GB) |  |
| `tsfm_public.toolkit.get_model:get_model` | ✓ | — | ✓ (`init --probe` config, 4.3 GB) |  |
| `stable_baselines3:PPO` | ✓ | — | ✓ (`init --probe` config, 4.5 GB) |  |
| `surfaces.test_functions.machine_learning.hyperparameter_optimization.tabular.regression.test_functions.gradient_boosting_regressor:GradientBoostingRegressorFunction` | ✓ | — | ✓ (seeded config, 613.9 MB) |  |
| `torchani.models:ANI2x` | ✓ | — | ✓ (`init --probe` config, 4.4 GB) |  |

---

## GEKKO models

Dynamic optimization and simulation models built on GEKKO, FMI 2, checked against a direct run and against each model's published results where it has them. GEKKO's distillation script and APMonitor's ethanol script have nothing to call, so their code is wrapped in a class, unchanged.

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `distillation_column.py:DistillationColumn` (GEKKO [`examples/distillation.py`](https://github.com/BYU-PRISM/GEKKO/blob/master/examples/distillation.py)) | ✓ | — | ✓ (`init --probe` config, 62.1 MB) | Distillation column (GEKKO's example, wrapped in a class with its equations unchanged). `--call step`. |
| `DistColEnvDynInc_altrewards.py:DistColEnvDynInc` ([Kalpesh-RL/DistillationColumn](https://github.com/Kalpesh-RL/DistillationColumn) `f2b9966`) | ✓ | — | ✓ (seeded config, 63.1 MB) | Distillation column as a Gym environment. `--start "Action=[0.0, 0.0, 0.0]" --setup reset`. Random by design: seed it (`random:seed(0)`, `numpy.random:seed(0)` before construction) to reproduce a run. |
| `Bioreactor.py:SimpleBioreactor` ([Bartosz1280/Bioreactor-modeling](https://github.com/Bartosz1280/Bioreactor-modeling) `3112aba`) | ✓ | — | ✓ (`init --probe` config, 97.8 MB) | Batch bioreactor (Monod growth). `--call solve`, `time_arr` and `simulation_input` from the repo notebook. |
| `Code/model.py:CGE` ([konradarchicinski/cge_model_python](https://github.com/konradarchicinski/cge_model_python) `60d611d`) | ✓ | — | ✓ (`init --probe` config, 64 MB, Windows) | Computable general equilibrium economy. `--call results --start capital=0.1 --start labour=0.0`. **Needs its `Code/model.py` renamed** (any other name): `build` refuses a model file named `model.py`, which clashes with UniFMU's backend module. **Needs pandas 2**: with pandas 3 the model itself fails (its chained `df[a][b] = …` assignments don't write under copy-on-write). **Windows only**: its data paths are hardcoded with backslashes (`Data\production_structure.csv`), which on Linux are file names that FMPy refuses in an FMU. |
| `CFTOCSolverV2.py:CFTOCSolverV2` ([ollyme102b/ros_workspace](https://github.com/ollyme102b/ros_workspace) `03f5938`) | ✓ | ✓ ([config](match-testing-rerun/configs/gk_cftoc.toml)) | ✓ (`init --probe` config, [identical to the direct run](probe-9/CONCLUSION.md)) | Constrained finite-time optimal control. `--call calculate_optimal_actuation`. `init --probe` with the repo test's values as `--start` (`x0`, `Xm` and the method's `calculate_optimal_actuation_x0`, `calculate_optimal_actuation_Xm` as `call:numpy:…`) writes the same config as the hand one; y = (−1.7×10⁻⁷, −7.7×10⁻⁴, 0) at t = 1, as the hand config. Before the fix, `init` refused the method's prefixed `call:` starts. |
| `debutanizer.model:solve_steady_state` ([Arushan45/Debutanizer-Project](https://github.com/Arushan45/Debutanizer-Project) `f6fe813`) | ✓ | — | ✓ (`init --probe` config, 57 MB) | Debutanizer column, steady state (30 stages). `--start reflux_ratio=2.5 --start alpha=1.9717789099`. **The repository must be installed** (`pip install -e .`): the entry is a package imported by name. |
| `debutanizer.model:optimize_reflux` ([Arushan45/Debutanizer-Project](https://github.com/Arushan45/Debutanizer-Project) `f6fe813`) | ✓ | — | ✓ (`init --probe` config, 57 MB) | Debutanizer reflux optimization. `--start alpha=1.9717789099`. **The repository must be installed**, as for the steady state. |
| `apsis/mpc.py:solve_mpc` ([dhruvhaldar/apsis](https://github.com/dhruvhaldar/apsis) `a171cf1`) | ✓ | — | ✓ (`init --probe` config, 62.1 MB) | Linear MPC. The app's defaults. |
| `process_fopdt.py:ProcessModel` ([BYU-PRISM/Transformer_MPC](https://github.com/BYU-PRISM/Transformer_MPC) `7686735`) | ✓ | — | ✓ (`init --probe` config, 130 MB with matplotlib and scipy) | 2×2 FOPDT process (a `GEKKO` subclass). `--call run --start "u=[1.0, 0.5]"`. |
| `mpc_gekko.py:MPCModel` ([BYU-PRISM/Transformer_MPC](https://github.com/BYU-PRISM/Transformer_MPC) `7686735`) | ✓ | — | ✓ (`init --probe` config, 62.1 MB) | MPC controller for that process (a `GEKKO` subclass). `--call solve`. Its setpoints are attributes (`y1.SP`): bind an input with `to = "attr:y1.SP"` by hand. |
| `ethanol_run.py:EthanolBioreactor` ([APMonitor](https://apmonitor.com/do/index.php/Main/EthanolBioreactor)) | ✓ | — | ✓ (`init --probe` config, 62.1 MB) | Ethanol fed-batch bioreactor (APMonitor's script, wrapped in a class: `run()` holds the script's code up to its `solve()`, unchanged, without the plots). `--call run`. The script's model can only be solved once, so `run()` builds it again each step. |
| `simple_nhes.py:model` ([BYU-PRISM/NHES-opt-sensitivity](https://github.com/BYU-PRISM/NHES-opt-sensitivity) `5e9a6f2`) | ✓ | — | ✓ (`init --probe` config, 128.5 MB) | Nuclear-renewable hybrid energy system. `--probe --start "params=call:simple_nhes:nom_params"`. **Needs input data that isn't published** (`grid_data/more_data_scaled.csv`): it was run on a generated series of hourly `Load`, `Wind` and `Solar` in MW. Also needs seaborn and plotly, which it imports without declaring. |
| `openhens:OpenHENS` ([waikato-ahuora-smart-energy-systems/OpenHENS](https://github.com/waikato-ahuora-smart-energy-systems/OpenHENS) `5081bab`) | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/gk_openhens.toml): one output added, `TAC = { from = "attr:_best_solns.0.case.TAC" }`) | ✓ (hand config, 118 MB; couenne must be on PATH) | Heat exchanger network synthesis. `--call solve`, the README's options. **Needs the COIN-OR `couenne` executable on PATH** (from the [IDAES solver bundle](https://github.com/IDAES/idaes-ext/releases/tag/3.4.2)) and **the repository installed** (`pip install -e .`), as its README says. `init --probe` finds no outputs: the solutions are kept in a private list; the hand config adds the total annual cost. It also reads the solutions saved in its `output_folder`, which `init` doesn't copy into the FMU, so its result differs from running it in the repository. |

**Compiling GEKKO models:** with PyInstaller, in a venv with only the model's packages, fmugen, PyInstaller and FMPy, a GEKKO model compiles in 10–25 s to 57–130 MB (matplotlib, which some model files import, adds about 35 MB). In a shared venv with many other packages, a compile took 19 min and made a 195 MB FMU: fmugen collects every gekko submodule, and some of them import scikit-learn, Pyomo and IPython when installed. Nuitka builds with gekko and numpy took over 30 minutes and were stopped. The compiled FMU contains gekko's own solver; a solver the model runs from PATH (OpenHENS's couenne) must be installed where the FMU runs.

---

## Hand configs

Configs written by hand where `init` can't infer everything. They are linked from the **Hand config** column. The ones not shown here are in [match-testing-rerun/configs](match-testing-rerun/configs/), each with a comment saying what it changes and why. `PropsSI`'s is [shown in models.md](models.md#positional-only-arguments).

### fluids.units

`Reynolds` and `head_from_P` take and return pint quantities: each input gets `convert = "pint"` and a `unit`, and `head_from_P`'s output `unit = "cm"`. Write the units the way pint reads them (`kg/m**3`, `Pa*s`, `m/s**2`): pint rejects the Modelica spelling (`kg/m3`, `Pa.s`), and fmugen then writes no `<BaseUnit>` for them. Checked: `Reynolds` gives 76401.3 and `head_from_P` 1019.7 cm, the values of `fluids.units` called directly.

### JOS3

Inputs bound to attributes (`to = "attr:tdb"`, …) and `setup = ["options.update({'limit_dshiv/dt': True})"]`; `init` writes `globals` for the module state `PRE_SHIV`. Checked: 40 one-minute steps at 10 °C give the core temperature of JOS3 run directly, also after a rollback.

### PyTCI

```toml
[model]
entry = "PyTCI.models.propofol:Marsh"
fmi_version = 2
call = "wait_time"

[parameters]
weight = { start = 70.0 }

[inputs]
time_seconds = { start = 1, type = "Integer" }
dose = { start = 2.0, unit = "mg", to = "call:give_drug" }

[outputs]
x1 = {}
x2 = {}
x3 = {}
xeo = {}
```

The model advances by `time_seconds`, not by the FMI step size. `give_drug` adds a bolus each time it's called, and a `to = "call:…"` setter runs once per step: 60 steps give 60 doses.

The first dose is given at initialization, so the outputs at t = 0 already include it: x1 = 2 mg / (0.228 L/kg × 70 kg) = 0.1253. The first step doesn't give it again. A loop that gives each dose at the start of its step (`give_drug(dose); wait_time(1)`) shows x1 = 0 at t = 0; from t = 1 the two are equal.

### Cantera

```toml
[model]
entry = "cantera:Solution"
fmi_version = 3
call = "equilibrate"
setup = ["__setattr__('TPX', (300.0, 101325.0, 'CH4:1, O2:2, N2:7.52'))"]

[parameters]
infile = { start = "gri30.yaml" }

[inputs]
XY = { start = "HP" }

[outputs]
T = { unit = "K" }
P = { unit = "Pa" }
density = {}
mean_molecular_weight = {}
```

The fuel/air state can only be set in `setup`: Cantera's `TPX` is a tuple property, and there is no way to bind inputs to it.

### metpy

```toml
[inputs]
temperature = { start = 25.0, unit = "degC", convert = "pint" }
relative_humidity = { start = 0.5, unit = "dimensionless", convert = "pint" }

[outputs]
y = { from = "return", unit = "degC" }
```

---

## Second batch

99 more models from libraries not in the tables above, tested the same way: 44 neural networks and 55 other models, 25 of them FMI 3 (Binary images, 2-D arrays, UInt64, and models listed for clocks and structural parameters). TabPFN was left out: it downloads its weights only after a license is accepted interactively, so it can't run unattended. The scripts, wrappers, hand configs and results are in [pending-100/](pending-100/): `run100.py` runs every step, `results.json` has every model's verdicts and versions.

Each model went through `fmugen init`, `fmugen init --probe`, `build --capture-output` and FMPy for 3 s with 1 s outputs on each config, a direct run of the model from the same config (twice, to find models random by design; those were compared seeded), and `build --compile pyinstaller` on the best matching config, compared with its uncompiled FMU. Setup: fmugen at `0a7c525` (unmodified), WSL 2 (Ubuntu 26.04), Python 3.13, one `uv` venv per model, torch 2.14.1 CPU build, FMPy 0.3.32, UniFMU 0.14, PyInstaller 6.22.3. Inputs: ultralytics' `bus.jpg` and `zidane.jpg`, the ONNX model zoo's MNIST, 5 s of whisper's `jfk.flac`, EPANET's `Net1.inp`, pyswmm's `model_weir_setting.inp`.

**Models that need a wrapper count as failures.** 29 libraries have no single function or class that is a model: the model is assembled in code (a do-mpc controller, a CasADi NLP, a FiPy mesh and equation, an OpenSees script, a GluonTS predictor, a right-hand side for `odeint`), or the results are read through methods. `init` has nothing to point at. Each was also tried through a short file written for this test, in [pending-100/wrappers](pending-100/wrappers/), calling the library as its documentation does; the notes say what the wrapper did and whether fmugen handled it.

| | Models (99) |
|---|---|
| **Simulates with useful results** (a config from `init` or `init --probe`) | **44** |
| …or with a hand-written config | **51** |
| Fails | **48**: 29 need a wrapper; 19 on fmugen problems, below |
| **Compiled FMU simulates, identical to the uncompiled one** | **40**; 11 more simulate uncompiled only |

Every matching config is identical to the model run directly: 51 974 values compared, largest relative difference 0.

**fmugen problems found.** Each failure below comes from one of these (some models that also need a wrapper hit one too). fmugen has since been fixed for each, with tests; with the fixes, every model failing on one of these passes, except py-pde's compiled FMU ([Known problems](#known-problems)) and skorch, which is random by design.

- **`build` refuses a config `init --probe` wrote** (10 models: nbeats, timesfm, skorch, tabnet, pyod, osqp, prophet, xgboost, lightgbm, catboost): a `setup` call with a call as argument (`fit(numpy.array(...))`) runs in the probe, but `build` accepts only literals and names.
- **Lists of integers are typed Real** (5: deepxde, fno, tcn, neuromancer, kan): torch refuses float sizes (`layer_sizes=[1, 16, 16, 1]`). An int scalar default is typed Integer.
- **`init --probe` finds no outputs** (3) for `bytes` (rembg; FMI 3 has Binary), a pandas Series indexed by dates (pastas), numpy arrays of `dtype=object` holding numbers (mtcnn).
- **`init --probe` writes invalid TOML** when a comment quotes a multi-line error (why the object can't be pickled): wav2vec2 fails, do-mpc works through its plain `init` config.
- **An output named `time` is hidden in FMI 2** (nengo): FMPy's results name the simulation time `time`, so the simulator's clock shows 1.0 instead of 0.01. FMI 3 configs rename it `model_time`.
- **Compiled FMUs fail to instantiate without an error message** (12): the backend exits and `--capture-output` keeps its traceback in the capture file, so UniFMU reports "no output". Underneath: torchvision's `_C_stable.so`, loaded by path, isn't collected (timm, ultralytics, easyocr); code-only package folders don't exist in the frozen app, so paths through them fail (chgnet's `model/../pretrained`, speechbrain); TorchScript needs the `.py` sources of the functions it compiles (mace, norse, matgl); ray imports its `_private` modules by name (neuralforecast).

Others found with earlier start values, which the configs above avoid: a `call:` value with text after its `)` (`pathlib:Path('x.png').read_bytes()`) silently calls `Path()` (rembg and easyocr got a `PosixPath`); `init` crashed on a class as an argument default (`TypeError: '>' not supported between 'getset_descriptor' and 'int'`: numpy's `default_rng` with a `size` start, reservoirpy with a 2-D input); a factory annotated with a base class crashes plain `init` (tirex: `AttributeError: forecast`); a `--start` named like the `**kwargs` parameter is refused (MOMENT's `model_kwargs`). These are fixed too.

### Neural networks (second batch)

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `ultralytics:YOLO` (FMI 3) | ✗ no useful outputs | ✓ ([config](pending-100/hand/yolo/fmugen.toml)) | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: torchvision's `_C_stable.so`, loaded by path, isn't collected. YOLO11n on ultralytics' `bus.jpg`. `predict` returns `Results` objects whose detections are tensors (`results[0].boxes.xyxy`): the hand config reads the 5 boxes, classes and confidences. |
| `transformers:pipeline` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). Passes with the fixes. `"sentiment-analysis"` (DistilBERT SST-2), `--call __call__`: label and score. Plain `init` stops: the object the factory returns is only known by running it. |
| `sentence_transformers:SentenceTransformer` | ✓ | — | ✓ (`init --probe` config, 2.9 GB) | `all-MiniLM-L6-v2`, `--call encode`: the 384-value embedding. |
| `timm:create_model` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: torchvision's `_C_stable.so`, loaded by path, isn't collected. `resnet18`, pretrained, on a 224×224 image tensor: 1000 logits. |
| `torchvision.models:resnet18` | ✓ | — | ✓ (`init --probe` config, 298.1 MB) | ImageNet weights on a 224×224 image tensor: 1000 logits. |
| `nf_nhits.py:NHitsForecast` (neuralforecast) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: ray imports `ray._private` modules by name. Wrapper ([nf_nhits.py](pending-100/wrappers/nf_nhits.py)): neuralforecast fits on a DataFrame and a `NeuralForecast` object, which `init` can't build. N-HiTS trained 5 steps, seeded; forecasts 4 values. |
| `darts.models:NBEATSModel` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. `--setup "fit(darts.TimeSeries.from_values(numpy.array([...])))"`, `--call predict`: 2 epochs, seeded. **Needs `darts[torch]`**: plain `darts` gives placeholders for its torch models. |
| `pf_tft.py:TFTForecast` (pytorch-forecasting) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([pf_tft.py](pending-100/wrappers/pf_tft.py)): the Temporal Fusion Transformer is built from a `TimeSeriesDataSet` and trained with a Lightning `Trainer`. Hidden size 8, 1 epoch, seeded. |
| `gluon_deepar.py:DeepARForecast` (gluonts) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([gluon_deepar.py](pending-100/wrappers/gluon_deepar.py)): the estimator trains into a predictor that takes GluonTS datasets. 1 epoch, seeded; mean forecast of 4 values. |
| `timesfm:TimesFM_2p5_200M_torch` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. TimesFM 2.5 (200M), `--create from_pretrained --call forecast` with `--setup "compile(timesfm.ForecastConfig(max_context=64, max_horizon=8))"` (a setup call with a call as argument). Point and quantile forecasts of 4 values. |
| `moirai_fc.py:MoiraiForecaster` (uni2ts) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([moirai_fc.py](pending-100/wrappers/moirai_fc.py)): Moirai's `forward` takes GluonTS-prepared tensors; its documented use is `create_predictor`. Moirai 1.0 R small, zero-shot, median of 20 seeded samples. **uni2ts pins numpy 1.26**, which has no Python 3.13 wheels: installed with `--no-deps`. |
| `momentfm:MOMENTPipeline` | ✓ | — | ✓ (`init --probe` config, 1.2 GB) | MOMENT-1-small, `--create from_pretrained --call forward`, `model_kwargs={'task_name': 'reconstruction'}`, `--setup init`: the reconstruction of a 512-point input. **momentfm pins numpy 1.25**: installed with `--no-deps`. |
| `tirex:load_model` | ✓ | — | ✓ (`init --probe` config, 1.1 GB) | `load_model("NX-AI/TiRex")`, `--call forecast` on a 24-point series: quantiles and mean of 4 values. |
| `mace.calculators:mace_mp` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: TorchScript needs the `.py` sources of the functions it compiles at import. MACE-MP-0 small, `--call get_potential_energy` on ASE's fcc copper. |
| `chgnet.model:CHGNet` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: chgnet opens `chgnet/model/../pretrained/…`, and `model/` doesn't exist in the frozen app (code-only folder). `--create load --call predict_structure` on fcc aluminium (pymatgen): energy, forces, stress, magnetic moments. |
| `matgl.ext.ase:PESCalculator` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: TorchScript needs the `.py` sources of the functions it compiles at import. TensorNet-PES-MatPES-PBE-2025.2 through its ASE calculator (`matgl.ext.ase:PESCalculator`, `--call get_potential_energy`) on fcc aluminium: −3.7124 eV. `load_model` returns a `Potential` with no `predict_structure`. |
| `deepxde.nn:FNN` | ✗ simulate fails | — | — | **Fails: the integer list start is typed Real**, so the model gets float sizes (`empty(): argument 'size' must be tuple of ints`). Passes with the fixes (integer lists typed Integer). A 1-16-16-1 tanh network (PyTorch backend, `DDE_BACKEND=pytorch`). Random weights: compared seeded (`torch:manual_seed(0)` in `setup`). |
| `neuralop.models:FNO` | ✗ simulate fails | — | — | **Fails: the integer list start is typed Real**, so the model gets float sizes (`empty(): argument 'size' must be tuple of ints`). Passes with the fixes (integer lists typed Integer). Fourier neural operator, 8 modes, on a 16-point input. Random weights: compared seeded. |
| `neural_ode.py:NeuralODE` (torchdiffeq) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([neural_ode.py](pending-100/wrappers/neural_ode.py)): `odeint` needs a right-hand side `f(t, y)` written as code. A seeded 2-16-2 MLP, integrated over each step with dopri5. |
| `torchdyn.core:NeuralODE` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). Passes with the fixes. `NeuralODE` around a `torch.nn.Linear(2, 2)` vector field. Random weights: compared seeded. |
| `sbi_gauss.py:Posterior` (sbi) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([sbi_gauss.py](pending-100/wrappers/sbi_gauss.py)): NPE needs simulations and a training run before it gives a posterior. Trained on 500 seeded simulations; the posterior mean for an observation. |
| `onnxruntime:InferenceSession` | ✓ | — | ✓ (`init --probe` config, 76.5 MB) | The ONNX model zoo's MNIST network, `--call run` with `input_feed=call:builtins:dict(Input3=numpy.zeros(...))`: 10 logits. |
| `keras.applications:MobileNetV2` | ✓ | — | ✓ (`init --probe` config, 283.0 MB) | MobileNetV2 (ImageNet), `--call predict`, **Keras on its JAX backend** (`KERAS_BACKEND=jax`): TensorFlow needs protobuf ≥ 5.28 and fmugen pins 5.27.3 (UniFMU 0.14's). |
| `equinox.nn:MLP` | ✓ | — | ✓ (`init --probe` config, 273.1 MB) | A 2-8-8-1 MLP, seeded by its `PRNGKey(0)`. |
| `skorch:NeuralNetRegressor` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. A `torch.nn.Linear(4, 1)` behind `NeuralNetRegressor`, `fit` in `setup`, `--call predict`. |
| `pytorch_tabnet.tab_model:TabNetRegressor` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. `fit` in `setup` (3 epochs, seeded), `--call predict`. **Needs pandas installed by hand.** |
| `facenet_pytorch:MTCNN` | ✗ no useful outputs | — | ✗ instantiate fails | **Fails: `init --probe` finds no output**: boxes and probabilities are numpy arrays of `dtype=object`. Passes with the fixes. **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output").  Face detection on ultralytics' `zidane.jpg`: 3 boxes and probabilities (numpy arrays of `dtype=object`). |
| `whisper:load_model` | ✓ | — | ✓ (`init --probe` config, 735.9 MB) | `tiny`, `--call transcribe` on 5 s of whisper's `jfk.flac` (16 kHz numpy array): the text. A file path needs ffmpeg. |
| `speechbrain.inference.speaker:EncoderClassifier` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: speechbrain lists its `utils/` folder, which doesn't exist in the frozen app. ECAPA speaker embedding, `--create from_hparams --call encode_batch`: 192 values. |
| `w2v_asr.py:Wav2Vec2ASR` (torchaudio) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: **Fails: `init --probe` writes invalid TOML**: a comment quotes a multi-line error (why the object can't be pickled). Plain `init` types the transcript as Real. Passes with the fixes. Wrapper ([w2v_asr.py](pending-100/wrappers/w2v_asr.py)): the pretrained model is a bundle constant's `get_model()`, and CTC decoding is code. The transcript of the speech clip. |
| `stable_baselines3:SAC` | ✓ | — | ✓ (`init --probe` config, 295.5 MB) | SAC on Pendulum from the Hugging Face hub (`sb3/sac-Pendulum-v1`), `--create load --call predict`. **Needs gym and shimmy**: the saved model unpickles with them. |
| `sb3_contrib:RecurrentPPO` | ✓ | — | ✓ (`init --probe` config, 291.9 MB) | LSTM PPO on CartPole (`sb3/ppo_lstm-CartPoleNoVel-v1`), `--create load --call predict`: action and LSTM states, carried between steps. **Needs gym and shimmy.** |
| `d3rlpy.algos:CQLConfig` | ✓ | — | ✓ (`init --probe` config, 346.4 MB) | `CQLConfig(...).create()`: the CQL algorithm object's settings. |
| `snntorch:Leaky` | ✓ | — | ✓ (`init --probe` config, 280.4 MB) | A leaky integrate-and-fire neuron with its hidden state: spikes and membrane potential between steps. |
| `norse.torch:LIFCell` | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: TorchScript needs the `.py` sources of the functions it compiles at import. LIF cell, `--call forward` with `input_tensor`: spikes, voltage and current. |
| `nengo:Simulator` | ✗ wrong values | — | ✗ wrong values, as uncompiled | **Fails: the output `time` (the simulator's clock) shows the simulation time** in FMPy's results, which name the simulation time `time`: 1.0 instead of 0.01. Passes with the fixes (renamed `model_time`). `nengo.Simulator` of an empty network, `--call run_steps`. |
| `reservoirpy.nodes:Reservoir` | ✓ | — | ✓ (`init --probe` config, 91.1 MB) | A 10-unit reservoir, `--call step` on a 1-D input. |
| `pytorch_tcn:TCN` | ✗ simulate fails | — | — | **Fails: the integer list start is typed Real**, so the model gets float sizes (`empty(): argument 'size' must be tuple of ints`). Passes with the fixes (integer lists typed Integer). Causal TCN with channels `[4, 4]` on a 16-point input. Random weights: compared seeded. |
| `kan:KAN` | ✗ simulate fails | — | — | **Fails: `width=[2, 3, 1]` is typed Real** (`'float' object is not subscriptable`). Passes with the fixes. A 2-3-1 KAN (grid 3, k 3, seed 0). **Needs scikit-learn, pandas, matplotlib, pyyaml and tqdm installed by hand.** |
| `ncps.torch:CfC` | ✓ (seeded) | — | ✓ (seeded config, 283.0 MB) | Closed-form continuous-time network, 8 units, on a 4-step sequence. Random weights: compared seeded. |
| `neuromancer.modules.blocks:MLP` | ✗ simulate fails | — | — | **Fails: the integer list start is typed Real**, so the model gets float sizes (`empty(): argument 'size' must be tuple of ints`). Passes with the fixes (integer lists typed Integer). A 2-8-1 MLP block. Random weights: compared seeded. **Needs wandb installed by hand.** |
| `pyod.models.auto_encoder:AutoEncoder` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. Autoencoder detector, `fit` in `setup` on 40 rows, `--call decision_function`. With 8 rows its training loop fails (`loss` unbound). |
| `rembg:remove` (FMI 3) | ✗ no useful outputs | — | ✓ simulates (no outputs) | **Fails: `init --probe` finds no output**: the result is `bytes`, which could be an FMI 3 Binary output. Passes with the fixes. U²-Net background removal: PNG bytes in, PNG bytes out. |
| `easyocr:Reader` (FMI 3) | ✓ | — | ✗ instantiate fails | **Compiled FMU fails to instantiate, with no error message** (`--capture-output` hides it: "backend exited unexpectedly … no output"). With the fixes: torchvision's `_C_stable.so`, loaded by path, isn't collected. OCR of a rendered `FMUGEN 2026` image (bytes): the text. |

### Other models (second batch)

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `qrcode:make` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 62.6 MB) | `make("fmugen")`: the QR image's properties (size, box size, …). |
| `pyzbar.pyzbar:decode` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 59.6 MB) | Decodes the QR image: `fmugen`. **Needs the zbar library** (`libzbar0t64`, here extracted without root and found through `LD_LIBRARY_PATH`). |
| `PIL.ImageOps:grayscale` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 57.6 MB) | A 64×64 image to grayscale: the image's properties. |
| `python_speech_features:mfcc` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 87.0 MB) | MFCC matrix of 5 s of speech: 499 × 13 (FMI 3 2-D array). |
| `ssqueezepy:ssq_cwt` (FMI 3) | ✗ simulate fails | ✓ ([config](pending-100/hand/ssq_cwt/fmugen.toml)) | ✓ (hand config, 156.0 MB) | Synchrosqueezed CWT of a 64-sample sine. `init` binds the argument `t` (the signal's time vector, default None) to the FMU time, so the model gets a float: the hand config leaves `[time]` out and outputs the 162 frequencies and scales. |
| `harold:lqr` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 116.5 MB) | LQR of a 2-state system: gain K (1×2), Riccati solution X (2×2), closed-loop eigenvalues (complex, split). **Needs numpy < 2.3** (harold imports `numpy.linalg.linalg`, removed in 2.3; FMPy needs ≥ 2.1.3). |
| `slycot:sb02md` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 69.7 MB) | `sb02md`, the continuous Riccati equation (SLICOT, Fortran): X, eigenvalues, condition. |
| `mpc_do.py:DoubleIntegratorMPC` (do-mpc) (FMI 3) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([mpc_do.py](pending-100/wrappers/mpc_do.py)): a do-mpc model and controller are built by method calls. Double-integrator MPC, horizon 10; `make_step` gives the control. Not on a clock: run at the communication step. Through the plain `init` config: `init --probe` writes invalid TOML (a comment quoting casadi's multi-line pickling error), fixed in the fixes. |
| `casadi_ocp.py:DoubleIntegratorOCP` (casadi) (FMI 3) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([casadi_ocp.py](pending-100/wrappers/casadi_ocp.py)): the NLP is built from CasADi expressions. Horizon N = 10 (a parameter, not structural); IPOPT; first control and cost. |
| `osqp:OSQP` (FMI 3) | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. `--setup "setup(scipy.sparse.csc_matrix(...), ...)"`, `--call solve`: the QP's solution and info. Not on a clock. |
| `ruckig_axis.py:Axis` (ruckig) (FMI 3) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([ruckig_axis.py](pending-100/wrappers/ruckig_axis.py)): Ruckig's methods are C built-ins taking parameter objects. One axis, 10 ms control cycle run inside each step: position, velocity, acceleration. |
| `vqf_imu.py:Orientation` (vqf) (FMI 3) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([vqf_imu.py](pending-100/wrappers/vqf_imu.py)): `VQF` is a C built-in, and the orientation comes from a method (`getQuat6D()`). 100 Hz samples inside each step. |
| `simdkalman:KalmanFilter` (FMI 3) | ✗ no useful outputs | ✓ ([config](pending-100/hand/simdkalman/fmugen.toml)) | ✓ (hand config, 48.9 MB) | Kalman smoother of a 24-point series. `smooth` returns a `Result` whose estimates are two levels down (`result.observations.mean`): the hand config reads them (24 levels, 24×2 states). |
| `fusion_ahrs.py:Orientation` (imufusion) (FMI 3) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([fusion_ahrs.py](pending-100/wrappers/fusion_ahrs.py)): `Ahrs` is a C built-in, and the orientation comes from a method (`get_quaternion()`). 100 Hz samples inside each step. |
| `pde:DiffusionPDE` (FMI 3) | ✓ | — | ✗ FMU fails | `DiffusionPDE`, `--call evolution_rate` on a 16-cell scalar field. **Compiled FMU fails**: py-pde loads `pde/backends/*/config.py` by path, and a compiled FMU ships no `.py` files. |
| `fipy_heat.py:Rod` (fipy) (FMI 3) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([fipy_heat.py](pending-100/wrappers/fipy_heat.py)): a FiPy problem is a mesh, variables and an equation built in code. 1-D heat equation, 10 cells. |
| `skfem:MeshTri` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 90.5 MB) | `MeshTri().refined(2)`: the refined mesh's nodes and elements (2-D arrays). |
| `pydmd:DMD` (FMI 3) | ✗ simulate fails | ✓ ([config](pending-100/hand/pydmd/fmugen.toml)) | ✓ (hand config, 145.8 MB) | DMD with 2 modes of 8 snapshots. The `init --probe` config reads DMD's properties at initialization, before `fit()` has run; the hand config runs `fit()` then too (`init_call = true`): eigenvalues and amplitudes, complex, split. |
| `numpy.random:default_rng` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 48.8 MB) | `default_rng(seed=12345678901234567890)`, `--call random`: the seed is a UInt64 parameter (FMI 3). |
| `pysindy:SINDy` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 99.9 MB) | SINDy fitted to two decaying exponentials: the coefficient matrix (2×10). |
| `mujoco_pendulum.py:Pendulum` (mujoco) (FMI 3) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([mujoco_pendulum.py](pending-100/wrappers/mujoco_pendulum.py)): MuJoCo steps a model and its data with `mj_step(model, data)`, C built-ins. A motor-driven pendulum: angle and velocity. |
| `wntr.sim:EpanetSimulator` (FMI 3) | ✓ | — | ✓ (`init --probe` config, 146.0 MB) | EPANET simulation of `Net1.inp`: pressures at the network's junctions (2-D, time × node). |
| `pymoo.optimize:minimize` | ✓ | — | ✓ (`init --probe` config, 134.0 MB) | NSGA-II on ZDT1, 5 generations, seed 1: the Pareto set and front. |
| `diffrax_decay.py:decay` (diffrax) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([diffrax_decay.py](pending-100/wrappers/diffrax_decay.py)): an ODE term is a Python function. dy/dt = −ky with Tsit5. |
| `sde_ou.py:ou` (sdeint) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([sde_ou.py](pending-100/wrappers/sde_ou.py)): the drift and diffusion are Python functions. An Ornstein–Uhlenbeck process, seeded. |
| `jit_osc.py:Oscillator` (jitcode) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([jit_osc.py](pending-100/wrappers/jit_osc.py)): the ODE is SymPy expressions compiled to C. A damped oscillator. |
| `pinocchio:rnea` | ✗ no config | ✓ ([config](pending-100/hand/pinocchio/fmugen.toml)) | ✓ (hand config, 90.0 MB) | Inverse dynamics (`rnea`) of the sample manipulator: Boost.Python functions with no signature, so `init` stops. The hand config passes model and data as positional constants and q, v, a by position. |
| `bullet_drop.py:BoxDrop` (pybullet) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([bullet_drop.py](pending-100/wrappers/bullet_drop.py)): `stepSimulation` returns nothing; the state is read with functions. A box dropped on a plane in `DIRECT` mode. **No wheel for Python 3.13**: built from source (here with zig's C++ compiler, `-fno-sanitize=undefined`). |
| `skrf.media:DefinedGammaZ0` | ✓ | — | ✓ (`init --probe` config, 107.0 MB) | A 90° line (`DefinedGammaZ0.line`) at 3 frequencies: S-parameters, complex, split. |
| `prophet:Prophet` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. `fit` on 24 days in `setup` (a DataFrame built by a setup call), `--call predict` for 2 days. |
| `statsforecast.models:AutoARIMA` | ✓ | — | ✓ (`init --probe` config, 225.3 MB) | AutoARIMA, `--call forecast`, h = 4. |
| `pmdarima:auto_arima` | ✓ | — | ✓ (`init --probe` config, 135.8 MB) | `auto_arima`, `--call predict`. |
| `lifelines:KaplanMeierFitter` | ✓ | — | ✓ (`init --probe` config, 142.5 MB) | Kaplan–Meier, `--call fit`: the survival function. |
| `mcmc_gauss.py:GaussMCMC` (emcee) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([mcmc_gauss.py](pending-100/wrappers/mcmc_gauss.py)): the log-probability is a Python function. 8 walkers, seeded; the running posterior mean. |
| `chaospy:Normal` | ✓ | — | ✓ (`init --probe` config, 92.0 MB) | `Normal(0, 1)`, `--call pdf`. |
| `sobol_ishigami.py:ishigami_sobol` (SALib) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([sobol_ishigami.py](pending-100/wrappers/sobol_ishigami.py)): Sobol analysis needs a sample and the model's outputs on it. First-order and total indices of the Ishigami function. |
| `pvwatts.py:pvwatts` (nrel-pysam) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([pvwatts.py](pending-100/wrappers/pvwatts.py)): `Pvwattsv8.default("PVWattsNone")` is a C built-in, and the model needs weather data set as an attribute. A 4 kW system, a synthetic year. |
| `floris_farm.py:Farm` (floris) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([floris_farm.py](pending-100/wrappers/floris_farm.py)): the farm's conditions are set with `set()` before `run()`. 3 turbines: powers and farm power. |
| `pypsa_pf.py:power_flow` (pypsa) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([pypsa_pf.py](pending-100/wrappers/pypsa_pf.py)): a network is built with `add()` calls. AC power flow of 2 buses. |
| `pipes_flow.py:gas_flow` (pandapipes) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([pipes_flow.py](pending-100/wrappers/pipes_flow.py)): `pipeflow(net)` returns nothing and writes its results onto `net`, as pandapower's `runpp`. Gas flow in the meshed delta network. |
| `pyswmm:Simulation` | ✓ | — | ✓ (`init` config, 46.1 MB) | `Simulation(inputfile)`, `--call __next__`: steps pyswmm's `model_weir_setting.inp`. The `init --probe` config fails (it reads the current time before the simulation starts); plain `init` works. |
| `pastas:Model` | ✗ no useful outputs | — | ✓ simulates (no outputs) | **Fails: `init --probe` finds no output**: the result is a pandas Series indexed by dates. Passes with the fixes (read as an array). `Model(oseries)`, `--call simulate`. |
| `landlab_flow.py:Hillslope` (landlab) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([landlab_flow.py](pending-100/wrappers/landlab_flow.py)): a grid and its fields are built in code. Flow accumulation on a 5×5 grid. |
| `tespy_hx.py:heater` (tespy) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([tespy_hx.py](pending-100/wrappers/tespy_hx.py)): a TESPy network is components and connections built in code. A water heater's outlet temperature. |
| `xgboost:XGBRegressor` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. `fit` in `setup`, `--call predict`. **Compiled: needs hypothesis installed**: PyInstaller imports every xgboost submodule, and `xgboost.testing` calls `pytest.importorskip("hypothesis")`, whose exception stops PyInstaller. |
| `lightgbm:LGBMRegressor` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. `fit` in `setup`, `--call predict`. **Needs scikit-learn installed by hand.** |
| `catboost:CatBoostRegressor` | ✗ build fails | — | — | **Fails: `build` refuses the config `init --probe` wrote**: its `setup` has a call as an argument (`fit(numpy.array(...))`), which the probe ran (`[model] setup …: arguments must be literals or names`). Passes with the fixes. `fit` in `setup`, `--call predict`. |
| `GPy.models:GPRegression` | ✓ | — | ✓ (`init --probe` config, 119.4 MB) | GP regression, `--call predict`: mean and variance. **Needs matplotlib installed by hand.** |
| `hapsira.twobody:Orbit` | ✓ | — | ✓ (`init --probe` config, 237.2 MB) | `Orbit.from_classical` (astropy units), `--call propagate` 600 s. **Needs numpy < 2.4** (`numpy.in1d`) **and astropy < 7** (`matrix_product`). |
| `opensees_cantilever.py:cantilever` (openseespy) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([opensees_cantilever.py](pending-100/wrappers/opensees_cantilever.py)): an OpenSees model is a script of module-level commands. A cantilever's tip deflection and base moment. |
| `pynite_beam.py:beam` (PyNiteFEA) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([pynite_beam.py](pending-100/wrappers/pynite_beam.py)): the model is built with method calls. A simply supported beam. |
| `section_rect.py:rectangle` (sectionproperties) | ✗ no model to point `init` at | — | ✗ (wrapper only) | **Fails: the library has no function or class that is the model**, so `init` has nothing to point at. Tried through a wrapper written for this test: Wrapper ([section_rect.py](pending-100/wrappers/section_rect.py)): the geometry must be meshed (`create_mesh`) before the `Section` is made. A 100×50 rectangle. |
| `arch:arch_model` | ✓ | — | ✓ (`init --probe` config, 122.9 MB) | `arch_model(y)`, `--call fit`: the GARCH fit's parameters. |
| `ephem:Sun` | ✗ no useful outputs | ✓ ([config](pending-100/hand/ephem/fmugen.toml)) | ✓ (hand config, 46.6 MB) | `Sun`, `--call compute`: the position is in C attributes that exist only after `compute()`; the hand config reads them, with `init_call = true`. |
| `sympy:lambdify` | ✗ simulate fails | ✓ ([config](pending-100/hand/sympy_lambdify/fmugen.toml)) | ✓ (hand config, 64.9 MB) | `lambdify` makes a function of x and y by position, which `init` can't see; the hand config binds them with `to = "pos:N"`. |

---

## Known problems

- **The backend outlives a failed FMU.** FMPy's `simulate_fmu` raises without calling `freeInstance`, so the UniFMU backend (`main.py`, 2 processes) keeps running and holds the importer's stdout/stderr; anything reading it through a pipe hangs. Not fmugen's: [fmpy-limitations.md §1](fmpy-limitations.md#1-simulate_fmu-doesnt-free-the-instance-after-an-fmu-error), and UniFMU's part in [unifmu-limitations.md §2](unifmu-limitations.md#2-the-backend-keeps-running-after-an-fmu-error). Workaround: free the instance yourself (`simulate_fmu(…, fmu_instance=fmu)`, then `fmu.freeInstance()` in a `finally`).
- **`fmpy simulate` shows no reason for a failure**, only the failed FMI call. The traceback shows with `simulate_fmu(…, debug_logging=True, logger=print)`. With FMI 2, a log message containing `%` (a URL, a traceback, Pyomo's log) can then crash FMPy: [unifmu-limitations.md §12](unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings).
- **Module-level scripts can't be models**: a script that solves at import time has nothing to call (GEKKO's distillation example, the ethanol bioreactor). Wrapping its code in a class works.
- **Windows long paths:** cantera and pybamm failed to import from a venv in a deeply nested folder. The FMU runs with the build venv, so deeply nested project folders may hit this.
- **`--convert` is refused for a step method's argument given by its prefixed name** (`--convert calculate_optimal_actuation_x0=…`): `--convert names that are not arguments of the model`. A `call:` start (`--start calculate_optimal_actuation_x0=call:numpy:array(…)`) works instead.
- **A local package imported by name isn't put in the FMU.** An entry like `debutanizer.model:solve_steady_state` or `openhens:OpenHENS`, from a cloned repository that isn't installed, is found by `init` only because it runs in that folder. The FMU's backend runs elsewhere and fails to import it. Installing the repository (`pip install -e .`) works; `init` gives no warning. Packages installed from PyPI aren't affected.
- **Files the model reads from a folder it computes aren't put in the FMU.** `init` copies the files the code or the starts name by a path. OpenHENS also reads saved solutions from its `output_folder`, so its FMU gives a different TAC than running it in the repository (154853.86 against 159038.72).

- **A compiled FMU has no `.py` files**, so a library that reads its own source files by path fails compiled: py-pde loads `pde/backends/*/config.py` (it works uncompiled).
- **PyInstaller stops on xgboost** unless hypothesis is installed: it imports every xgboost submodule, and `xgboost.testing` calls `pytest.importorskip("hypothesis")`, whose exception isn't an `Exception`.
- **`init` binds an argument named `t` to the FMU time**, also when it is a time vector (ssqueezepy's `ssq_cwt(x, t=None)`): remove `[time]` from the config.

Limitations (not bugs):

- **An output's size can't change during the simulation.** FMI variables have fixed sizes (FMI 3 arrays resize only through structural parameters), so an output that becomes `None` or changes length fails the step instead of giving wrong values. `init --probe` comments out the ones it sees change.
- **Model files named `model.py`** are refused by `build`: the name clashes with UniFMU's backend module. Rename the file; `init` warns about it.


---

## Versions

The versions are in [match-testing-rerun/results.json](match-testing-rerun/results.json) (`versions`): the latest on PyPI for Python 3.13 when the venvs were made. Pinned where it mattered: pandas 2.3.3 for the CGE model, `setuptools<81` for heartpy.

Only RC_BuildingSimulator (commit `97c1cdd`, MIT amended) is copied into this repository, for [examples/rc_building](../examples/rc_building). The others are installed from PyPI or their repositories when needed.

---

## Reproducing a run

1. Install fmugen in an environment together with the model's library.
2. Run `init` with the options from the table.
3. Build and check the FMU.

For example, for `fluids`:

```bash
fmugen init fluids.friction:friction_factor --start Re=1e5 -o -
```

Write the config with `-o path/to/fmugen.toml` instead of `-o -`, then:

```bash
fmugen build path/to/fmugen.toml -o out/friction.fmu
```

Add `--fmi 3` to `init` or `build` for FMI 3.

Run these from an environment with fmugen and `fluids` installed (`pip install path/to/2025_Inkindcontributions fluids`; fmugen is not on PyPI yet). The FMU runs with that environment (see [packaging.md](packaging.md#the-fmus-python-environment)).
