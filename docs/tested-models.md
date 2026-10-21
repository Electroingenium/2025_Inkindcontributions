# Tested models

fmugen has been tried on 130+ published, unmodified Python models: the examples in this repository, models from more than 100 libraries on PyPI, 6 neural networks and 16 models built on [GEKKO](https://github.com/BYU-PRISM/GEKKO). Each model is listed once, with its most recent result.

- [How the models were tested](#how-the-models-were-tested)
- [Summary](#summary)
- [Repository examples](#repository-examples)
- [Python libraries](#python-libraries)
- [Neural networks](#neural-networks)
- [GEKKO models](#gekko-models)
- [Hand configs](#hand-configs)
- [Known problems](#known-problems)
- [Deployment with Liqo](#deployment-with-liqo)
- [Versions](#versions)
- [Reproducing a run](#reproducing-a-run)

---

## How the models were tested

Each model went through:

1. `fmugen init` (code only)
2. `fmugen init --probe`
3. `fmugen build --capture-output` on each config `init` wrote (and on the committed `fmugen.toml` for the repository examples), then `fmpy.simulate_fmu` for 3 s with 1 s outputs
4. `fmugen build --capture-output --compile pyinstaller` on the best config (the `--probe` one when it simulated), then the same simulation

**FMI 2 by default.** A model was run with FMI 3 only when no FMI 2 config simulated; the results below combine both. Errors were recorded first and fixed afterwards; rows show the result after the fixes, with the date when it is later than the main run.

Setup: Windows 11, Python 3.13, `uv` venvs, fmugen editable from this checkout, FMPy 0.3.32, PyInstaller 6.22.3, UniFMU 0.14. The library and neural-network models were run on 2026-10-09 at `0e0b670`, with fixes and reruns up to 2026-10-13; the GEKKO models on 2026-10-13 and 2026-10-14 (gekko 1.3.2, local solver).

Columns: **`init` / `init --probe`**: ✓ if the config of either one builds, simulates and outputs the model's results; otherwise how they failed (✗ no useful outputs: it runs, but only outputs parameters, settings or constants). **Hand config**: a config written by hand (for the examples, the repository's `fmugen.toml`), ✓ if it builds, simulates and outputs the model's results, with a link to it; — when the model needs none: ✓, ✗ no config (`init` stopped), ✗ build fails, ✗ simulate fails, or — (not run). **Compiled**: the best config compiled with PyInstaller, built and simulated. **Notes**: what was checked, or the error of each config that failed ("`init`:", "`init --probe`:").

---

## Summary

Libraries, neural networks and repository examples: 118 models, each with an `init` run. FMI 2 and FMI 3 results are combined: a model counts as passing if it passes with either.

| | Count |
|---|---|
| `init` writes a config | 113 |
| `init --probe` writes a config | 117 |
| **Simulates with useful results** (a config from `init` or `init --probe`) | **95** |
| …or with a hand-written config | **102** |
| Fails | 16 |
| **Compiled FMU simulates** | **96**: every model that simulates with an `init`, `init --probe` or repository config |

A config only counts as a success if the FMU simulates **and** gives the model's results. An FMU that runs but only outputs its own parameters, settings or constants counts as a failure.

How far each step gets:

| Config | Simulates correctly | Success |
|---|---|---|
| `init` (code only) | 44 of 118 | 37 % |
| `init --probe` (or `init`, when it already works) | 95 of 118 | 81 % |
| `init --probe` + a hand-written config (for the examples, the repository's `fmugen.toml`) | 102 of 118 | 86 % |

The `init` config fails mostly on models that return arrays, tuples, strings or objects, which only `--probe` types correctly; the error message points to it. Of the 67 `init` configs that simulate, 23 only output parameters, settings or constants. The hand configs add `PropsSI`, `fluids.units` ×2, metpy, cantera, PyTCI and the kalman example ([Hand configs](#hand-configs)); they were checked on 2026-10-06/07, not in the 2026-10-09 rerun.

The 16 failures: sgp4 (a C built-in with no signature: hand config not written yet), pyet (needs pandas Series), psychrolib (a numba ufunc takes no keyword arguments), simpy (`until` not bound to time), pyquaternion (`*args` constructor gets the step's arguments), nashpy (the method returns a generator), and 10 that simulate but give no useful results: ambiance, pandapower, pymunk, seirsplus, impedance, pybamm, river, commpy, tellurium and uncertainties.

GEKKO models (16), counted the same way:

| Config | Simulates correctly | Success |
|---|---|---|
| `init` (code only) | 1 of 16 | 6 % |
| `init --probe` (or `init`, when it already works) | 9 of 16 | 56 % |
| `init --probe` + a hand-written config | 9 of 16 | 56 % |

GEKKO models keep their results in GEKKO variables, which only `--probe` finds. Of the 7 failures, CGE only needs its `model.py` renamed; ethanol and transmembrane fail without fmugen too; drilling, NHES, needforheat and OpenHENS need inputs, data or solvers that aren't available.

---

## Repository examples

| Model | `init` / `init --probe` | Hand config (the repository's `fmugen.toml`) | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| [examples/psychrometry](../examples/psychrometry) (`compute_balances_simplified`) | ✓ | ✓ | ✓ (hand config, 128.7 MB) | 6 outputs. `init -o` outside the model's folder now stops with a `fmugen: error` naming where to write the config. |
| [examples/simple_pid](../examples/simple_pid) (`simple_pid:PID`) | ✓ | ✓ | ✓ (`init --probe` config, 128.7 MB) |  |
| [examples/rc_building](../examples/rc_building) (`Zone`) | ✓ | ✓† | ✓† (hand config, 128.7 MB) | †The repo config fixes `step_size = 3600`, so the generic 1 s run is refused (correct); simulated at 3600 s steps, plain and compiled give the same values. |
| [examples/kalman](../examples/kalman) (`filterpy.kalman:KalmanFilter`; repo config FMI 3: structural parameters, clock) | ✗ no useful outputs | ✓ | ✓ (hand config, rebuilt 2026-10-13) | The `init` configs output only filter settings and likelihoods (`dim_x`, …, `alpha`, `likelihood`), not the state estimate. The repository config drives the filter correctly with `examples/kalman/run.py`, compiled too. |
| [examples/sampled_pid](../examples/sampled_pid) (`simple_pid:PID`; repo config: clocks) | ✓ | ✓ | ✓ (hand config, 128.7 MB) | 2026-10-21: the repo config driven by `run.py` (clock ticked every 0.1 s, first-order plant) brings the output to 0.78 → 1.0 setpoint; the `init` and `init --probe` configs of `simple_pid:PID` build and simulate. |

---

## Python libraries

Errors such as `y is an array of shape […], not a single value` in the `init` config are expected: `--probe` finds the shape.

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `ahrs.filters:Madgwick` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `ahrs.filters:Mahony` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `ambiance:Atmosphere` | ✗ no useful outputs | — | ✗ no useful outputs | Outputs only echo the inputs (`h`, `check_bounds`); the results are properties returning 1-element arrays, which `init` doesn't see. |
| `anastruct:SystemElements` | ✓ | — | ✓ (`init --probe` config, 52.5 MB) |  |
| `antropy:perm_entropy` | ✓ | — | ✓ (`init --probe` config, 105.7 MB) |  |
| `astral.sun:elevation` | ✓ | — | ✓ (`init --probe` config, 101.9 MB) |  |
| `astropy.cosmology:FlatLambdaCDM` | ✓ | — | ✓ (`init --probe` config, 37.7 MB) |  |
| `Bio.SeqUtils:gc_fraction` | ✓ | — | ✓ (`init --probe` config, 29.8 MB) |  |
| `blackscholes:BlackScholesCall` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `cantera:Solution` | ✗ no useful outputs | ✓ ([config](#cantera)) | ✗ no useful outputs | Outputs are only solver settings (`rtol`, `max_steps`): the results are Cython properties, and the gas state can't be set from inputs. The hand config works. |
| `chemicals.vapor_pressure:Antoine` | ✓ | — | ✓ (`init --probe` config, 134.6 MB) |  |
| `colour.temperature:CCT_to_xy_CIE_D` | ✓ | — | ✓ (`init --probe` config, 113.1 MB) |  |
| `commpy.modulation:QAMModem` | ✗ no useful outputs | — | ✗ no useful outputs | Only output: `m = 4`. The modulated symbols are complex, so they're left out. |
| `control:StateSpace` | ✓ | — | ✓ (`init --probe` config, 2026-10-13) | y = (0, −2) = A·x with `--start x=[1.0, 0.0] --start u=[0.0]`. |
| `CoolProp.CoolProp:PropsSI` | ✗ build fails | ✓ ([config](models.md#positional-only-arguments)) | ✗ build fails (`init --probe` config) | C extension with no signature: no variables inferred. Needs a hand config ([below](#hand-configs)). |
| `cv2:KalmanFilter` | ✓ | — | ✓ (`init --probe` config, 66.3 MB) |  |
| `dysts:Lorenz` (`call = "rhs"`, `[model] integrate`) | — | ✓ | — | 2026-10-14: dysts 0.96's `Lorenz().rhs(X, t)` integrated by the FMU, 20 steps of 0.05 s, against `solve_ivp` at 1e-11: largest difference 1.3 × 10⁻⁶ with `"scipy:DOP853"` (FMI 3) and 3.3 × 10⁻⁸ with `"rk4"`, 50 substeps (FMI 2). |
| `electricpy:powerset` | ✓ | — | ✓ (`init --probe` config, 71.2 MB) |  |
| `erfa:gmst06` | ✓ | — | ✓ (`init --probe` config, 101.8 MB) |  |
| `filterpy.common:Q_discrete_white_noise` | ✓ | — | ✓ (`init --probe` config, 128.8 MB) |  |
| `filterpy.gh:GHFilter` | ✓ | — | ✓ (`init --probe` config, 128.8 MB) |  |
| `fluids.core:Reynolds` | ✓ | — | ✓ (`init --probe` config, 133.8 MB) |  |
| `fluids.friction:friction_factor` | ✓ | — | ✓ (`init --probe` config, 133.8 MB) |  |
| `fluids.units:head_from_P` | ✗ simulate fails | ✓ ([config](#fluidsunits)) | ✗ simulate fails (`init --probe` config, 133.8 MB) | TypeError: 100000.0 has no quantity |
| `fluids.units:Reynolds` | ✗ simulate fails | ✓ ([config](#fluidsunits)) | ✗ simulate fails (`init --probe` config, 133.8 MB) | TypeError: 1.0 has no quantity |
| `gsw:rho` | ✓ | — | ✓ (`init --probe` config, 103.3 MB) |  |
| `gymnasium.envs.classic_control.cartpole:CartPoleEnv` | ✓ | — | ✓ (`init --probe` config, 135.6 MB) |  |
| `gymnasium.envs.classic_control.pendulum:PendulumEnv` | ✓ | — | ✓ (`init --probe` config, 135.6 MB) |  |
| `haversine:haversine` | ✓ | — | ✓ (`init --probe` config, 24.6 MB) |  |
| `heartpy:process` | ✓ | — | ✓ (`init --probe` config, 2026-10-13) | With its `data/data.csv` given by full path: 20 variables, bpm 58.9 (compiled too). Imports `pkg_resources`: needs `setuptools<81`. |
| `highway_env.envs.highway_env:HighwayEnv` | ✓ | — | ✓ (`init --probe` config, 135.8 MB) |  |
| `hplib.hplib:HeatPump` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `ht.conv_internal:Nu_conv_internal` | ✓ | — | ✓ (`init --probe` config, 134.1 MB) |  |
| `ht.hx:effectiveness_from_NTU` | ✓ | — | ✓ (`init --probe` config, 134.1 MB) |  |
| `iapws.iapws97:_TSat_P` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) | 2026-10-14: with `discard_on = ["builtins:NotImplementedError"]`, a step at 30 MPa returns `discard`; the output keeps 453.04 K, and the step retried at 2 MPa succeeds (485.53 K). |
| `iapws:IAPWS97` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `impedance.models.circuits:Randles` | ✗ no useful outputs | — | ✗ no useful outputs | Outputs only echo `initial_guess`; the complex prediction is left out (commented as real/imaginary parts). |
| `joblib:load` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `librosa:hz_to_mel` | ✓ | — | ✓ (`init --probe` config, 108.5 MB) |  |
| `mendeleev:element` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) | `init --probe`: 79 variables; Fe gives atomic_number 26, atomic_weight 55.845. |
| `mesa.examples:BoltzmannWealth` | ✓ | — | ✓ (`init --probe` config, 111.4 MB) |  |
| `meteocalc:heat_index` | ✓ | — | ✓ (`init --probe` config, 24.6 MB) |  |
| `metpy.calc:dewpoint_from_relative_humidity` | ✗ simulate fails | ✓ ([config](#metpy)) | ✗ simulate fails (`init --probe` config, 111.0 MB) | ValueError: This function changed in version(s) ['1.0']--double check that the function is being called properly. |
| `nashpy:Game` | ✗ simulate fails | — | — | 0.0.43 has no `is_zero_sum`; with `support_enumeration` the method returns a generator: `--probe` finds no outputs, the `init` config fails (`float() argument must be … not 'generator'`). |
| `neurokit2:ecg_simulate` | ✓ | — | ✓ (`init --probe` config, 114.1 MB) |  |
| `numdifftools:Derivative` | ✓ | — | ✓ (`init --probe` config, 52.3 MB) |  |
| `numpy_financial:pmt` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `obspy.geodetics:gps2dist_azimuth` | ✓ | — | ✓ (`init --probe` config, 77.0 MB) |  |
| `openap:Thrust` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `openturns:Normal` | ✓ | — | ✓ (`init --probe` config, 79.9 MB) |  |
| `pandapower:runpp` | ✗ no useful outputs | — | ✗ no useful outputs | Outputs are only solver settings (`tolerance_mva`, `calculate_voltage_angles`): the results are DataFrames written onto the network argument. |
| `pedon:Genuchten` | ✓ | — | ✓ (`init --probe` config, 83.7 MB) |  |
| `ppigrf:igrf` | ✓ | — | ✓ (`init --probe` config, 101.5 MB) |  |
| `psychrolib:GetHumRatioFromRelHum` | ✗ simulate fails | — | ✗ simulate fails (`init --probe` config, 128.7 MB) | TypeError: unexpected keyword arguments to ufunc: 'Pressure', 'RelHum', 'TDryBulb' (a numba ufunc). With FMI 2 and logging on, FMPy then crashes on the `%s` in the traceback ([UniFMU §12](unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings)). |
| pvlib `get_total_irradiance` → `sapm_cell` → `pvwatts_dc` (**composite FMU**) | ✓ (each part) | — | ✓ (2026-10-14) | 2026-10-14: the three parts made with `init --probe`, built with `--compile pyinstaller`: the FMU holds no `.py` file, and three weather cases give values identical to calling pvlib in a chain. |
| `pvlib.atmosphere:alt2pres` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.iotools:read_tmy3` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.irradiance:aoi` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.pvsystem:pvwatts_dc` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.solarposition:get_solarposition` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.temperature:sapm_cell` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `py_vollib.black_scholes:black_scholes` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `pybamm:Simulation` | ✗ no useful outputs | — | ✗ no useful outputs | Outputs are only solver flags; the voltage can't be expressed as an output. |
| `PyCO2SYS:sys` | ✓ | — | ✓ (`init --probe` config, 24.8 MB) |  |
| `pyet:pm_fao56` | ✗ simulate fails | — | ✗ simulate fails (`init --probe` config, 111.1 MB) | AttributeError: 'float' object has no attribute 'time' |
| `pyfluids:Fluid` | ✓ | — | ✓ (`init --probe` config, 29.4 MB) |  |
| `pygfunction.heat_transfer:finite_line_source` | ✓ | — | ✓ (`init --probe` config, 52.8 MB) |  |
| `pykalman:KalmanFilter` | ✓ | — | ✓ (`init --probe` config, 52.5 MB) |  |
| `pyloudnorm:Meter` | ✓ | — | ✓ (`init` config, 53.2 MB) | `init --probe`: ValueError: blockwise_loudness has 0 values, expected 17 |
| `pymap3d:geodetic2enu` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `pymsis:calculate` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `pymunk:Space` | ✗ no useful outputs | — | ✗ no useful outputs | Outputs are only constant settings (`damping`, `collision_slop`, …); `gravity` (a `Vec2d`), `bodies` and `shapes` are left out. |
| `pyorbital.astronomy:sun_zenith_angle` | ✓ | — | ✓ (`init --probe` config, 25.0 MB) |  |
| `pyproj:Transformer` | ✓ | — | ✓ (`init --probe` config, 107.9 MB) |  |
| `pyquaternion:Quaternion` | ✗ simulate fails | — | ✗ simulate fails (`init --probe` config, 24.6 MB) | ValueError: Unexpected number of elements in sequence. Got: 2, Expected: 4. |
| `pyromat:get` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `pysolar.solar:get_altitude` | ✓ | — | ✓ (`init --probe` config, 101.5 MB) |  |
| `PyTCI.models.propofol:Marsh` | ✗ no useful outputs | ✓ ([config](#pytci)) | ✗ no useful outputs | Outputs only echo the parameters (`weight`, `time_seconds`): the state is in a nested function. The hand config works. |
| `pyteomics.mass:calculate_mass` | ✓ | — | ✓ (`init --probe` config, 28.4 MB) |  |
| `pythermalcomfort.models.jos3:JOS3` | ✓ | ✓ ([config](#jos3)) | ✓ (`init --probe` config, 128.9 MB) |  |
| `pythermalcomfort.models:pmv_ppd_iso` | ✓ | — | ✓ (`init --probe` config, 97.0 MB) |  |
| `pythermalcomfort.models:sports_heat_stress_risk` | ✓ | — | ✓ (`init --probe` config, 128.9 MB) |  |
| `pywt:dwt` | ✓ | — | ✓ (`init --probe` config, 25.2 MB) |  |
| `pyxirr:npv` | ✓ | — | ✓ (`init --probe` config, 25.0 MB) |  |
| `quantecon:LinearStateSpace` | ✓ | — | ✓ (`init --probe` config, 98.8 MB) |  |
| `QuantLib:blackFormula` | ✓ | — | ✓ (`init --probe` config, 37.2 MB) |  |
| `radioactivedecay:Inventory` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `rainflow:count_cycles` | ✓ | — | ✓ (`init --probe` config, 24.6 MB) |  |
| `rdkit.Chem.Descriptors:MolWt` | ✓ | — | ✓ (`init --probe` config, 44.7 MB) |  |
| `river.linear_model:LinearRegression` | ✗ no useful outputs | — | ✗ no useful outputs | Outputs are only hyperparameters (`l1`, `l2`, …), no prediction or weights. |
| `roboticstoolbox.models.DH:Panda` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `scipy.signal:lfilter` | ✓ | — | ✓ (`init --probe` config, 53.2 MB) |  |
| `seirsplus.models:SEIRSModel` | ✗ no useful outputs | — | ✗ no useful outputs | Outputs only echo the parameters (`beta`, `sigma`, `gamma`, …); the epidemic state arrays change size and are left out. |
| `sgp4.api:Satrec` | ✗ no config | ✗ not written yet | — | C built-ins with no signature: `--start fr, jd, line1, line2: cannot tell which arguments these are …`. Needs a hand config. |
| `shapely:Point` | ✓ | — | ✓ (`init --probe` config, 26.2 MB) |  |
| `simglucose.patient.t1dpatient:T1DPatient` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `simpy:Environment` | ✗ simulate fails | — | ✗ simulate fails (`init --probe` config, 24.7 MB) | ValueError: until (1.0) must be greater than the current simulation time |
| `skfuzzy:interp_membership` | ✓ | — | ✓ (`init --probe` config, 52.3 MB) |  |
| `skimage.color:rgb2hsv` | ✓ | — | ✓ (`init --probe` config, 52.8 MB) |  |
| `statsmodels.stats.proportion:proportion_confint` | ✓ | — | ✓ (`init --probe` config, 71.3 MB) |  |
| `tclab:TCLabModel` | ✓ | — | ✓ (`init --probe` config, 128.8 MB) |  |
| `tellurium:loada` | ✗ no useful outputs | — | ✗ no useful outputs | Only output: `oneStep`'s return (always 0.1, the step size), not the species. |
| `thermo:Chemical` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `thermofeel:calculate_heat_index_simplified` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `timezonefinder:TimezoneFinder` | ✓ | — | ✓ (`init --probe` config, 58.0 MB) |  |
| `tmm:coh_tmm` | ✓ | — | ✓ (`init --probe` config, 24.6 MB) |  |
| `transforms3d.euler:euler2quat` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `uncertainties:ufloat` | ✗ no useful outputs | — | ✗ no useful outputs | Only output: `s`, the standard deviation given as input; the nominal value is missing. |
| `windpowerlib.wind_speed:logarithmic_profile` | ✓ | — | ✓ (`init --probe` config, 101.5 MB) |  |

---

## Neural networks

Each was installed as published (`pip install <package>`) into its own venv together with fmugen. Neural networks need `--probe`: their result sizes depend on the weights, and their code is mostly compiled or framework code. Weights from Hugging Face are downloaded on first use, unless the FMU is built with `--hf-weights` (automatic with `--vendor` / `--compile`). `--capture-output` is needed whenever a model prints while loading, which hangs UniFMU 0.14 otherwise.

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `chronos:ChronosBoltPipeline` | ✓ | — | ✓ (`init --probe` config, 322.8 MB) |  |
| `silero_vad:load_silero_vad` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `tsfm_public.toolkit.get_model:get_model` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `stable_baselines3:PPO` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `surfaces.test_functions.machine_learning.hyperparameter_optimization.tabular.regression.test_functions.gradient_boosting_regressor:GradientBoostingRegressorFunction` | ✓ | — | ✓, 294 MB (recompiled 2026-10-13) (`init --probe` config) |  |
| `torchani.models:ANI2x` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |

---

## GEKKO models

Dynamic optimization and simulation models built on GEKKO, FMI 2, run on 2026-10-13/14 and checked against each model's published results where it has them. On 2026-10-14 GEKKO's distillation script (nothing to call) was reworked into a class (first row), and lighter published models (the debutanizer, MPC and FOPDT rows) were added next to those that fail for reasons of their own (the last 6 rows). Only the CFTOC model was compiled: the Nuitka builds were stopped after 30 minutes (see below).

| Model | Source | Entry and `init` options | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|---|---|
| Distillation column (GEKKO's example, reworked into a class; equations unchanged) | GEKKO [`examples/distillation.py`](https://github.com/BYU-PRISM/GEKKO/blob/master/examples/distillation.py) | `distillation_column.py:DistillationColumn`, `--call step` | ✓ | — | — | 7 outputs. At reflux 3.0 the condenser goes 0.785721, 0.837391, 0.867374 and the reboiler 0.190012, 0.145341, 0.120733: the script's own values. The original module-level script has nothing to call. |
| Distillation column as a Gym environment | [Kalpesh-RL/DistillationColumn](https://github.com/Kalpesh-RL/DistillationColumn) `f2b9966` | `DistColEnvDynInc_altrewards.py:DistColEnvDynInc`, `--start "Action=[0.0, 0.0, 0.0]" --setup reset` | ✓ | — | — | State, reward, `done` and message change every step; `D`, `B`, `FL` are outputs too (D = 1.133, B = 0.873). |
| Batch bioreactor (Monod growth) | [Bartosz1280/Bioreactor-modeling](https://github.com/Bartosz1280/Bioreactor-modeling) `3112aba` | `Bioreactor.py:SimpleBioreactor`, `--call solve`, `time_arr` and `simulation_input` from the repo notebook | ✓ | — | — | 5 outputs (`X`, `S`, `mu`, `dXdt`, `dSdt`) read from the GEKKO variables at the end of the horizon; X goes 0.0451 → 0.0444 g/L over 3 steps. |
| Computable general equilibrium economy | [konradarchicinski/cge_model_python](https://github.com/konradarchicinski/cge_model_python) `60d611d` | `Code/model.py:CGE`, `--call results --start capital=0.1 --start labour=0.0` | ✗ build fails | — | — | `build` refuses a model file named `model.py` (it clashes with UniFMU's backend; intended: rename the file). From a renamed copy: 27 outputs, the first step = the direct run (x3 supply 72.076, price 1.119). Needs pandas 2 (with pandas 3 the model itself fails). |
| Constrained finite-time optimal control | [ollyme102b/ros_workspace](https://github.com/ollyme102b/ros_workspace) `03f5938` | `CFTOCSolverV2.py:CFTOCSolverV2`, `--call calculate_optimal_actuation`, the repo test's starts, `--start calculate_optimal_actuation_x0=…` | ✓ | — | ✓ (`init --probe` config, 43 MB, 2 min) | y = (−0.09546, −0.02481, 0), then (−0.09521, −0.02558, 0) twice = the class called directly; the compiled FMU gives the same values. `--compile nuitka`: stopped after 30 min. |
| Debutanizer column, steady state (30 stages) | [Arushan45/Debutanizer-Project](https://github.com/Arushan45/Debutanizer-Project) `f6fe813` | `debutanizer.model:solve_steady_state`, `--start reflux_ratio=2.5 --start alpha=1.9717789099` | ✓ | — | — | C4 0.96999957519, vapor 133.0 kmol/h, duty 0.84972 MW: the repo's `results/summary.json` to all digits. |
| Debutanizer reflux optimization | same | `debutanizer.model:optimize_reflux`, `--start alpha=1.9717789099` | ✓ | — | — | Reflux 2.7602061381, purity 0.991, vapor 142.8878332478: the repo's optimum to all digits. |
| Linear MPC | [dhruvhaldar/apsis](https://github.com/dhruvhaldar/apsis) `a171cf1` | `apsis/mpc.py:solve_mpc`, the app's defaults | ✓ | — | — | (time, states, inputs) over the horizon: 21 + 42 + 21 outputs. |
| 2×2 FOPDT process (a `GEKKO` subclass) | [BYU-PRISM/Transformer_MPC](https://github.com/BYU-PRISM/Transformer_MPC) `7686735` | `process_fopdt.py:ProcessModel`, `--call run --start "u=[1.0, 0.5]"` | ✓ | — | — | y = (0.3333, 0.0833), (0.6111, 0.1528), (0.8426, 0.2106): K₁₁ = 2, K₂₂ = 1, τ = 5. Outputs list only the GEKKO variables, not GEKKO's own state (fixed 2026-10-14). |
| MPC controller for that process (a `GEKKO` subclass) | same repo | `mpc_gekko.py:MPCModel`, `--call solve` | ✓ | — | — | Runs, but with no setpoints its moves stay near 0. The setpoints are attributes (`y1.SP`): bind an input with `to = "attr:y1.SP"` by hand. |
| Ethanol fed-batch bioreactor | [APMonitor](https://apmonitor.com/do/index.php/Main/EthanolBioreactor) | `ethanol_bioreactor.py` | ✗ no config | — | — | A script: importing it runs its own solve, and GEKKO's local solver crashes (`Access Violation … ace.f90`), also when run directly. **Not fmugen's.** Now shown as a `fmugen: error` naming the line. |
| Cell transmembrane potential | [0xDBFB7/transmembrane_potential](https://github.com/0xDBFB7/transmembrane_potential) `165c86f` | `transmembrane_lib.py:gekko_sim_method`, `--kind function` | ✗ simulate fails | — | — | `NameError: name 'GEKKO' is not defined`: dead code upstream. **Not fmugen's.** |
| Directional drilling MPC | [Xiang-Gu/CS394R_RL_Directional_Drilling](https://github.com/Xiang-Gu/CS394R_RL_Directional_Drilling) `12a45cf` | `mpc/mpc.py:solveMPC`, `--call action --start "state=[0.0, 0.0, 0.0, 0.0]"` | ✗ simulate fails | — | — | The constructor takes a Gym environment object, which no FMU input can give; it also solves on APMonitor's server (`remote=True`). |
| Nuclear-renewable hybrid energy system | [BYU-PRISM/NHES-opt-sensitivity](https://github.com/BYU-PRISM/NHES-opt-sensitivity) `5e9a6f2` | `simple_nhes.py:model`, `--start params=<nom_params>` | ✗ simulate fails | — | — | Reads `grid_data/more_data_scaled.csv`, which isn't published. |
| Residential heat diagnosis | [energietransitie/needforheat-diagnosis-software](https://github.com/energietransitie/needforheat-diagnosis-software) `48d3a85` | `analysis/rhc_analysis.py:Model`, `--call building` | ✗ simulate fails | — | — | Methods written without `self`, and the input is a pandas DataFrame of measurements, which no FMU input can give. |
| Heat exchanger network synthesis | [waikato-ahuora-smart-energy-systems/OpenHENS](https://github.com/waikato-ahuora-smart-energy-systems/OpenHENS) `5081bab` | `openhens:OpenHENS`, `--call solve`, the README's options | ✗ simulate fails | — | — | `couenne solver not found`: needs the COIN-OR binaries on PATH. |

**Compiling GEKKO models:** with PyInstaller, a GEKKO model compiles in 2 min (43 MB) in a venv with only gekko, numpy, fmugen, PyInstaller and FMPy. In a shared venv with many other packages, the same compile took 19 min and made a 195 MB FMU: fmugen collects every gekko submodule, and some of them import scikit-learn, Pyomo and IPython when installed. **Compile a model in a venv with only what it needs.** Nuitka builds with gekko and numpy took over 30 minutes and were stopped; `examples/simple_pid` compiles with Nuitka and simulates (12 min).

---

## Hand configs

Configs written by hand where `init` can't infer everything. They are linked from the **Hand config** column; each was last checked on 2026-10-06/07 (dysts on 2026-10-14). `PropsSI`'s is [shown in models.md](models.md#positional-only-arguments).

### fluids.units

`Reynolds` and `head_from_P` take and return pint quantities: each input gets `convert = "pint"` and a `unit`, and `head_from_P`'s output `unit = "cm"`. Checked: `Reynolds` gives 76401.3 and `head_from_P` 1019.7 cm, the values of `fluids.units` called directly.

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

The model advances by `time_seconds`, not by the FMI step size. `give_drug` adds a bolus each time it's called, and a `to = "call:…"` setter runs at initialization and before every step: 60 steps give 61 doses.

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

## Known problems

Still open:

- **The backend outlives a failed FMU.** FMPy's `simulate_fmu` raises without calling `freeInstance`, so the UniFMU backend (`main.py`, 2 processes) keeps running and holds the importer's stdout/stderr; anything reading it through a pipe hangs. Not fmugen's: [fmpy-limitations.md §1](fmpy-limitations.md#1-simulate_fmu-doesnt-free-the-instance-after-an-fmu-error), and UniFMU's part in [unifmu-limitations.md §2](unifmu-limitations.md#2-the-backend-keeps-running-after-an-fmu-error). Workaround: free the instance yourself (`simulate_fmu(…, fmu_instance=fmu)`, then `fmu.freeInstance()` in a `finally`).
- **`fmpy simulate` shows no reason for a failure**, only the failed FMI call. The traceback shows with `simulate_fmu(…, debug_logging=True, logger=print)`. With FMI 2, a log message containing `%` (a URL, a traceback, Pyomo's log) can then crash FMPy: [unifmu-limitations.md §12](unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings).
- **Outputs whose type or size changes at run time fail the step** (a value that becomes `None`, an array whose length varies). `init --probe` comments them out with the reason.
- **`to = "call:…"` setters run once more than the steps**: harmless for setters that store a value, not for ones that accumulate ([PyTCI](#pytci)).
- **Methods that need simulation time aren't bound to it** (simpy `Environment.run(until)`).
- **An `*args` constructor gets the step method's `--start` values too** (pyquaternion).
- **`init` doesn't write `[model] requirements`**, which deployment images need.
- **Model files named `model.py`** are refused by `build` (intended: rename the file); `init` doesn't warn.
- **Windows long paths:** cantera and pybamm failed to import from a venv in a deeply nested folder. The FMU runs with the build venv, so deeply nested project folders may hit this.

---

## Deployment with Liqo

On 2026-10-07, about 50 of the library models (numpy_financial, QuantLib, pymap3d, shapely, librosa, mendeleev, tellurium, …) were also deployed across two kind clusters peered with Liqo v1.2.0. Each model's best config got `[model] requirements` and was built into an image with `docker/Dockerfile` (`MODEL=docker/models/r3/<name>`), then run as a Job on the virtual node `fmu-remote`, talking to the OPC UA server in `fmu-local` through the reflected Service. The configs are in `docker/models/r3/<name>/fmugen.toml`.

**Liqo itself caused no failures**: runs succeeded on `fmu-remote` exactly where they succeeded on Windows, with the same values. Exceptions: tellurium's Linux image lacked a dependency (`No module named 'tesbml'`), and antropy's run hung after connecting (cause not investigated). Class models showed `0` in the first row of the runner's CSV (t = 0), and the right value from t = 1.

---

## Versions

The latest on PyPI for Python 3.13 at the time of each run (2026-10-06 to 2026-10-14). Pinned where it mattered: pythermalcomfort 2.10 for needforheat (it imports `pmv_ppd`, removed in 3.x), pandas 2.3.3 for the CGE model, `setuptools<81` for heartpy.

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
