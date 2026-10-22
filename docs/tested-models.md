# Tested models

fmugen has been tried on 131 published, unmodified Python models (three needed a file renamed or a script wrapped in a class, and one synthetic input data; see their notes): the examples in this repository, models from more than 100 libraries on PyPI, 6 neural networks and 13 models built on [GEKKO](https://github.com/BYU-PRISM/GEKKO). Each model is listed once, with its most recent result.

- [How the models were tested](#how-the-models-were-tested)
- [Summary](#summary)
- [Repository examples](#repository-examples)
- [Python libraries](#python-libraries)
- [Neural networks](#neural-networks)
- [GEKKO models](#gekko-models)
- [Hand configs](#hand-configs)
- [Pending](#pending)
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

## Pending

100 more models, not tried yet: 45 neural networks and 55 other models, from libraries not in the tables above. 25 need FMI 3: Binary variables (images), 2-D arrays, clocks, structural parameters or UInt64. Every package is on PyPI; the entry and what to try are a starting point, not checked.

### Neural networks (pending)

| Model | Package | FMI 3 feature | What to try | Status |
|---|---|---|---|---|
| `ultralytics:YOLO` | [ultralytics](https://pypi.org/project/ultralytics/) | Binary | YOLO11n object detection; the image as a Binary input, boxes as arrays | pending |
| `transformers:pipeline` | [transformers](https://pypi.org/project/transformers/) | — | `"sentiment-analysis"` pipeline (DistilBERT): text in, label and score out | pending |
| `sentence_transformers:SentenceTransformer` | [sentence-transformers](https://pypi.org/project/sentence-transformers/) | — | `all-MiniLM-L6-v2`, `--call encode`: a 384-value embedding | pending |
| `timm:create_model` | [timm](https://pypi.org/project/timm/) | — | `resnet18`, pretrained: image classification logits | pending |
| `torchvision.models:resnet18` | [torchvision](https://pypi.org/project/torchvision/) | — | ImageNet weights, a 224×224 image | pending |
| `neuralforecast.models:NHITS` | [neuralforecast](https://pypi.org/project/neuralforecast/) | — | N-HiTS forecaster, fitted on a short series, `predict` | pending |
| `darts.models:NBEATSModel` | [darts](https://pypi.org/project/darts/) | — | N-BEATS forecaster | pending |
| `pytorch_forecasting:TemporalFusionTransformer` | [pytorch-forecasting](https://pypi.org/project/pytorch-forecasting/) | — | Temporal Fusion Transformer | pending |
| `gluonts.torch:DeepAREstimator` | [gluonts](https://pypi.org/project/gluonts/) | — | DeepAR probabilistic forecaster (`gluonts[torch]`) | pending |
| `timesfm:TimesFM_2p5_200M_torch` | [timesfm](https://pypi.org/project/timesfm/) | — | Google TimesFM 2.5 foundation forecaster (Hugging Face weights) | pending |
| `uni2ts.model.moirai:MoiraiForecast` | [uni2ts](https://pypi.org/project/uni2ts/) | — | Salesforce Moirai foundation forecaster | pending |
| `momentfm:MOMENTPipeline` | [momentfm](https://pypi.org/project/momentfm/) | — | MOMENT time-series foundation model | pending |
| `tirex:load_model` | [tirex-ts](https://pypi.org/project/tirex-ts/) | — | NX-AI TiRex (xLSTM) forecaster | pending |
| `mace.calculators:mace_mp` | [mace-torch](https://pypi.org/project/mace-torch/) | — | MACE-MP-0 interatomic potential (ASE calculator): energy and forces | pending |
| `chgnet.model:CHGNet` | [chgnet](https://pypi.org/project/chgnet/) | — | CHGNet crystal potential, `predict_structure` | pending |
| `matgl:load_model` | [matgl](https://pypi.org/project/matgl/) | — | M3GNet universal potential | pending |
| `deepxde.nn:FNN` | [deepxde](https://pypi.org/project/deepxde/) | — | Physics-informed network (PINN) | pending |
| `neuralop.models:FNO` | [neuraloperator](https://pypi.org/project/neuraloperator/) | — | Fourier neural operator | pending |
| `torchdiffeq:odeint` | [torchdiffeq](https://pypi.org/project/torchdiffeq/) | — | Neural ODE (an MLP right-hand side) | pending |
| `torchdyn.core:NeuralODE` | [torchdyn](https://pypi.org/project/torchdyn/) | — | Neural ODE module | pending |
| `sbi.inference:NPE` | [sbi](https://pypi.org/project/sbi/) | — | Neural posterior estimation (normalizing flow) | pending |
| `onnxruntime:InferenceSession` | [onnxruntime](https://pypi.org/project/onnxruntime/) | — | An ONNX model zoo network (MNIST), `--call run` | pending |
| `keras.applications:MobileNetV2` | [keras](https://pypi.org/project/keras/) | — | Keras/TensorFlow image classifier (needs tensorflow) | pending |
| `equinox.nn:MLP` | [equinox](https://pypi.org/project/equinox/) | — | JAX network | pending |
| `skorch:NeuralNetRegressor` | [skorch](https://pypi.org/project/skorch/) | — | A torch network behind a scikit-learn API, `predict` | pending |
| `pytorch_tabnet.tab_model:TabNetRegressor` | [pytorch-tabnet](https://pypi.org/project/pytorch-tabnet/) | — | TabNet on tabular data | pending |
| `tabpfn:TabPFNRegressor` | [tabpfn](https://pypi.org/project/tabpfn/) | — | TabPFN tabular foundation model | pending |
| `facenet_pytorch:MTCNN` | [facenet-pytorch](https://pypi.org/project/facenet-pytorch/) | — | Face detection | pending |
| `whisper:load_model` | [openai-whisper](https://pypi.org/project/openai-whisper/) | — | Speech to text (`tiny`), `--call transcribe`: a string output | pending |
| `speechbrain.inference.speaker:EncoderClassifier` | [speechbrain](https://pypi.org/project/speechbrain/) | — | Speaker embedding (ECAPA) | pending |
| `torchaudio.pipelines:WAV2VEC2_ASR_BASE_960H` | [torchaudio](https://pypi.org/project/torchaudio/) | — | wav2vec 2.0 speech recognition | pending |
| `stable_baselines3:SAC` | [stable-baselines3](https://pypi.org/project/stable-baselines3/) | — | SAC policy on Pendulum (`predict`) | pending |
| `sb3_contrib:RecurrentPPO` | [sb3-contrib](https://pypi.org/project/sb3-contrib/) | — | LSTM policy: its hidden state carried between steps | pending |
| `d3rlpy.algos:CQLConfig` | [d3rlpy](https://pypi.org/project/d3rlpy/) | — | Offline RL (CQL) policy | pending |
| `snntorch:Leaky` | [snntorch](https://pypi.org/project/snntorch/) | — | Spiking neuron layer: membrane state between steps | pending |
| `norse.torch:LIFCell` | [norse](https://pypi.org/project/norse/) | — | Spiking LIF cell, state between steps | pending |
| `nengo:Simulator` | [nengo](https://pypi.org/project/nengo/) | — | Spiking network simulator, `--call run_steps` | pending |
| `reservoirpy.nodes:Reservoir` | [reservoirpy](https://pypi.org/project/reservoirpy/) | — | Echo state network | pending |
| `pytorch_tcn:TCN` | [pytorch-tcn](https://pypi.org/project/pytorch-tcn/) | — | Temporal convolutional network, streaming mode | pending |
| `kan:KAN` | [pykan](https://pypi.org/project/pykan/) | — | Kolmogorov–Arnold network | pending |
| `ncps.torch:CfC` | [ncps](https://pypi.org/project/ncps/) | — | Liquid / closed-form continuous-time network | pending |
| `neuromancer.modules.blocks:MLP` | [neuromancer](https://pypi.org/project/neuromancer/) | — | Differentiable-programming control block | pending |
| `pyod.models.auto_encoder:AutoEncoder` | [pyod](https://pypi.org/project/pyod/) | — | Autoencoder anomaly detector, `decision_function` | pending |
| `rembg:remove` | [rembg](https://pypi.org/project/rembg/) | Binary | Background removal (U²-Net): image bytes in and out | pending |
| `easyocr:Reader` | [easyocr](https://pypi.org/project/easyocr/) | Binary | OCR: image bytes in, text out | pending |

### Other models (pending)

| Model | Package | FMI 3 feature | What to try | Status |
|---|---|---|---|---|
| `qrcode:make` | [qrcode](https://pypi.org/project/qrcode/) | Binary | QR code as PNG bytes out | pending |
| `pyzbar.pyzbar:decode` | [pyzbar](https://pypi.org/project/pyzbar/) | Binary | Barcode decoding from image bytes | pending |
| `PIL.ImageOps:grayscale` | [pillow](https://pypi.org/project/pillow/) | Binary | Image bytes in, grayscale image bytes out | pending |
| `python_speech_features:mfcc` | [python_speech_features](https://pypi.org/project/python_speech_features/) | 2-D array | MFCC matrix of an audio frame | pending |
| `ssqueezepy:ssq_cwt` | [ssqueezepy](https://pypi.org/project/ssqueezepy/) | 2-D array | Synchrosqueezed wavelet transform (complex, split) | pending |
| `harold:lqr` | [harold](https://pypi.org/project/harold/) | 2-D array | LQR gain matrix K | pending |
| `slycot:sb02md` | [slycot](https://pypi.org/project/slycot/) | 2-D array | Riccati solution matrix (SLICOT, Fortran) | pending |
| `do_mpc.controller:MPC` | [do-mpc](https://pypi.org/project/do-mpc/) | Clock | MPC sampled on a clock (`t_step`) | pending |
| `casadi:nlpsol` | [casadi](https://pypi.org/project/casadi/) | Structural parameter | Optimal control, horizon length N as a structural parameter | pending |
| `osqp:OSQP` | [osqp](https://pypi.org/project/osqp/) | Clock | QP-based MPC solved at each clock tick | pending |
| `ruckig:Ruckig` | [ruckig](https://pypi.org/project/ruckig/) | Clock | Jerk-limited trajectory generator at a fixed control cycle | pending |
| `vqf:VQF` | [vqf](https://pypi.org/project/vqf/) | Clock | IMU orientation filter, updated at the sensor's sample clock | pending |
| `simdkalman:KalmanFilter` | [simdkalman](https://pypi.org/project/simdkalman/) | Structural parameter | Vectorized Kalman filter, the state size as a structural parameter | pending |
| `imufusion:Ahrs` | [imufusion](https://pypi.org/project/imufusion/) | Clock | x-io Fusion AHRS, updated at a fixed sample clock | pending |
| `pde:DiffusionPDE` | [py-pde](https://pypi.org/project/py-pde/) | Structural parameter | Diffusion on a grid, the grid size as a structural parameter | pending |
| `fipy:Grid1D` | [fipy](https://pypi.org/project/fipy/) | Structural parameter | Finite-volume 1-D heat equation, `nx` cells | pending |
| `skfem:MeshTri` | [scikit-fem](https://pypi.org/project/scikit-fem/) | Structural parameter | FEM Poisson problem, mesh refinement sets the array sizes | pending |
| `pydmd:DMD` | [pydmd](https://pypi.org/project/pydmd/) | Structural parameter, 2-D array | Dynamic mode decomposition, number of modes | pending |
| `numpy.random:default_rng` | [numpy](https://pypi.org/project/numpy/) | UInt64 | A UInt64 seed | pending |
| `pysindy:SINDy` | [pysindy](https://pypi.org/project/pysindy/) | 2-D array | Sparse identification: the coefficient matrix | pending |
| `mujoco:MjData` | [mujoco](https://pypi.org/project/mujoco/) | Structural parameter | Physics model: arrays sized by `nq`, `nv` | pending |
| `wntr.sim:EpanetSimulator` | [wntr](https://pypi.org/project/wntr/) | Structural parameter | Water network: pressures sized by the number of junctions | pending |
| `pymoo.optimize:minimize` | [pymoo](https://pypi.org/project/pymoo/) | — | Multi-objective optimization (NSGA-II) | pending |
| `diffrax:diffeqsolve` | [diffrax](https://pypi.org/project/diffrax/) | — | JAX ODE solver | pending |
| `sdeint:itoint` | [sdeint](https://pypi.org/project/sdeint/) | — | Stochastic differential equation (seeded) | pending |
| `jitcode:jitcode` | [jitcode](https://pypi.org/project/jitcode/) | — | ODE compiled to C from SymPy expressions | pending |
| `pinocchio:buildSampleModelManipulator` | [pin](https://pypi.org/project/pin/) | — | Rigid-body dynamics (RNEA, ABA) | pending |
| `pybullet:connect` | [pybullet](https://pypi.org/project/pybullet/) | — | Physics engine in `DIRECT` mode | pending |
| `skrf:Network` | [scikit-rf](https://pypi.org/project/scikit-rf/) | — | RF network S-parameters (complex, split) | pending |
| `prophet:Prophet` | [prophet](https://pypi.org/project/prophet/) | — | Bayesian forecaster (Stan) | pending |
| `statsforecast.models:AutoARIMA` | [statsforecast](https://pypi.org/project/statsforecast/) | — | Fast ARIMA | pending |
| `pmdarima:auto_arima` | [pmdarima](https://pypi.org/project/pmdarima/) | — | ARIMA with model search | pending |
| `lifelines:KaplanMeierFitter` | [lifelines](https://pypi.org/project/lifelines/) | — | Survival analysis | pending |
| `emcee:EnsembleSampler` | [emcee](https://pypi.org/project/emcee/) | — | MCMC sampler (seeded) | pending |
| `chaospy:Normal` | [chaospy](https://pypi.org/project/chaospy/) | — | Polynomial chaos / uncertainty quantification | pending |
| `SALib.analyze.sobol:analyze` | [SALib](https://pypi.org/project/SALib/) | — | Sobol sensitivity indices | pending |
| `PySAM.Pvwattsv8:default` | [nrel-pysam](https://pypi.org/project/nrel-pysam/) | — | NREL SAM PV model (C library) | pending |
| `floris:FlorisModel` | [floris](https://pypi.org/project/floris/) | — | Wind farm wakes | pending |
| `pypsa:Network` | [pypsa](https://pypi.org/project/pypsa/) | — | Power flow (`pf`) | pending |
| `pandapipes:create_empty_network` | [pandapipes](https://pypi.org/project/pandapipes/) | — | Pipe network flow | pending |
| `pyswmm:Simulation` | [pyswmm](https://pypi.org/project/pyswmm/) | — | Stormwater (SWMM engine), stepped | pending |
| `pastas:Model` | [pastas](https://pypi.org/project/pastas/) | — | Groundwater time-series model | pending |
| `landlab.components:FlowAccumulator` | [landlab](https://pypi.org/project/landlab/) | — | Landscape flow routing on a grid | pending |
| `tespy.networks:Network` | [tespy](https://pypi.org/project/tespy/) | — | Thermal plant network (a heat pump cycle) | pending |
| `xgboost:XGBRegressor` | [xgboost](https://pypi.org/project/xgboost/) | — | Gradient boosting | pending |
| `lightgbm:LGBMRegressor` | [lightgbm](https://pypi.org/project/lightgbm/) | — | Gradient boosting | pending |
| `catboost:CatBoostRegressor` | [catboost](https://pypi.org/project/catboost/) | — | Gradient boosting | pending |
| `GPy.models:GPRegression` | [GPy](https://pypi.org/project/GPy/) | — | Gaussian process: mean and variance | pending |
| `hapsira.twobody:Orbit` | [hapsira](https://pypi.org/project/hapsira/) | — | Orbit propagation (astropy units) | pending |
| `openseespy.opensees:node` | [openseespy](https://pypi.org/project/openseespy/) | — | Structural FE (OpenSees), module-level state | pending |
| `Pynite:FEModel3D` | [PyNiteFEA](https://pypi.org/project/PyNiteFEA/) | — | 3-D frame FE analysis | pending |
| `sectionproperties.analysis:Section` | [sectionproperties](https://pypi.org/project/sectionproperties/) | — | Cross-section properties (FE) | pending |
| `arch:arch_model` | [arch](https://pypi.org/project/arch/) | — | GARCH volatility model, `fit` then `forecast` | pending |
| `ephem:Observer` | [ephem](https://pypi.org/project/ephem/) | — | Sun and planet positions from an observer (C library) | pending |
| `sympy:lambdify` | [sympy](https://pypi.org/project/sympy/) | — | A symbolic expression made into a function | pending |

---

## Known problems

- **The backend outlives a failed FMU.** FMPy's `simulate_fmu` raises without calling `freeInstance`, so the UniFMU backend (`main.py`, 2 processes) keeps running and holds the importer's stdout/stderr; anything reading it through a pipe hangs. Not fmugen's: [fmpy-limitations.md §1](fmpy-limitations.md#1-simulate_fmu-doesnt-free-the-instance-after-an-fmu-error), and UniFMU's part in [unifmu-limitations.md §2](unifmu-limitations.md#2-the-backend-keeps-running-after-an-fmu-error). Workaround: free the instance yourself (`simulate_fmu(…, fmu_instance=fmu)`, then `fmu.freeInstance()` in a `finally`).
- **`fmpy simulate` shows no reason for a failure**, only the failed FMI call. The traceback shows with `simulate_fmu(…, debug_logging=True, logger=print)`. With FMI 2, a log message containing `%` (a URL, a traceback, Pyomo's log) can then crash FMPy: [unifmu-limitations.md §12](unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings).
- **Module-level scripts can't be models**: a script that solves at import time has nothing to call (GEKKO's distillation example, the ethanol bioreactor). Wrapping its code in a class works.
- **Windows long paths:** cantera and pybamm failed to import from a venv in a deeply nested folder. The FMU runs with the build venv, so deeply nested project folders may hit this.
- **`--convert` is refused for a step method's argument given by its prefixed name** (`--convert calculate_optimal_actuation_x0=…`): `--convert names that are not arguments of the model`. A `call:` start (`--start calculate_optimal_actuation_x0=call:numpy:array(…)`) works instead.
- **A local package imported by name isn't put in the FMU.** An entry like `debutanizer.model:solve_steady_state` or `openhens:OpenHENS`, from a cloned repository that isn't installed, is found by `init` only because it runs in that folder. The FMU's backend runs elsewhere and fails to import it. Installing the repository (`pip install -e .`) works; `init` gives no warning. Packages installed from PyPI aren't affected.
- **Files the model reads from a folder it computes aren't put in the FMU.** `init` copies the files the code or the starts name by a path. OpenHENS also reads saved solutions from its `output_folder`, so its FMU gives a different TAC than running it in the repository (154853.86 against 159038.72).

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
