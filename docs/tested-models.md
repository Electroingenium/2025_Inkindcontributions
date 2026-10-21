# Tested models

fmugen has been tried on 131 published, unmodified Python models (three needed a file renamed or a script wrapped in a class, and one synthetic input data; see their notes): the examples in this repository, models from more than 100 libraries on PyPI, 6 neural networks and 13 models built on [GEKKO](https://github.com/BYU-PRISM/GEKKO). Each model is listed once, with its most recent result.

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

Setup: Windows 11, Python 3.13, `uv` venvs, fmugen editable from this checkout, FMPy 0.3.32, PyInstaller 6.22.3, UniFMU 0.14. The library and neural-network models were run on 2026-10-09 at `0e0b670`, with fixes and reruns up to 2026-10-13; the GEKKO models on 2026-10-13 and 2026-10-14 (gekko 1.3.2, local solver). Every model was rebuilt and compared with a direct run on 2026-10-22 at `6dfc18c`, in WSL 2 (Linux); see [the rerun report](match-testing-rerun/report.md).

Columns: **`init` / `init --probe`**: ✓ if the config of either one builds, simulates and outputs the model's results; otherwise how they failed (✗ no useful outputs: it runs, but only outputs parameters, settings or constants). **Hand config**: a config written by hand (for the examples, the repository's `fmugen.toml`), ✓ if it builds, simulates and outputs the model's results, with a link to it; — when the model needs none: ✓, ✗ no config (`init` stopped), ✗ build fails, ✗ simulate fails, or — (not run). **Compiled**: the best config compiled with PyInstaller, built and simulated. **Notes**: what was checked, or the error of each config that failed ("`init`:", "`init --probe`:").

---

## Summary

131 models: 118 from libraries, neural networks and the repository examples, and 13 built on GEKKO. FMI 2 and FMI 3 results are combined: a model counts as passing if it passes with either.

| | Models (131) |
|---|---|
| `init` writes a config | 125 |
| `init --probe` writes a config | 129 |
| **Simulates with useful results** (a config from `init` or `init --probe`) | **109** |
| …or with a hand-written config | **126** |
| Fails | 5 |
| **Compiled FMU simulates** | **97**: every model compiled when compiling was last tested (2026-10-13; one GEKKO model, CFTOC, was compiled) |

A config only counts as a success if the FMU simulates **and** gives the model's results. An FMU that runs but only outputs its own parameters, settings or constants counts as a failure.

How far each step gets:

| Config | Models | Success |
|---|---|---|
| `init` (code only) | 45 of 131 | 34 % |
| `init --probe` (or `init`, when it already works) | 109 of 131 | 83 % |
| `init --probe` + a hand-written config (for the examples, the repository's `fmugen.toml`) | 126 of 131 | 96 % |

The `init` config fails mostly on models that return arrays, tuples, strings or objects, which only `--probe` types correctly; the error message points to it. Of the 67 `init` configs of the first group that simulate, 23 only output parameters, settings or constants. GEKKO models keep their results in GEKKO variables, which only `--probe` finds. The hand configs add `PropsSI`, `fluids.units` ×2, metpy, cantera, PyTCI and the kalman example ([Hand configs](#hand-configs)), and since 2026-10-22 ambiance, pandapower, seirsplus, impedance, commpy, river, tellurium, uncertainties and the GEKKO models CFTOC and OpenHENS ([configs](match-testing-rerun/configs/)). All were checked against a direct run on 2026-10-22.

The 5 failures, by cause:

| Cause | Models | What it means |
|---|---|---|
| **Not supported by fmugen**: the model's inputs or results have a shape fmugen can't map to FMU variables | sgp4 (C built-ins with no signature; a hand config with `to = "pos:N"` bindings might work, not written yet), pyet (needs a pandas Series with a date index as input), nashpy (the method returns a generator) | A new fmugen feature, or for sgp4 a hand config. |
| **A path can't reach the result**: the result exists, but no `from` path can read it | pymunk (`Space.bodies` is a `dict_keys` view, which a path can't index), pybamm (the voltage is `solution["Voltage [V]"]` on an object that isn't a mapping) | Small fmugen features: indexing any iterable, and item access by key on objects with `__getitem__`. |
| **Model bug**: the published model doesn't run on its own | none (transmembrane, whose GEKKO class was dead code, is no longer listed) | |
| **Output mismatch**: the FMU runs but gives different values than the model run directly | none | Every model was compared value by value with a direct run: see below. |

**FMU vs direct run** ([2026-10-21 report](match-testing/report.md), [2026-10-22 rerun](match-testing-rerun/report.md)): every model was built into FMUs (`init --probe`, plain `init`, and the repository or hand configs; no `--compile`) and compared, output by output and step by step, with the model called directly in plain Python without fmugen. In the rerun, at `6dfc18c`, 130 of 134 models match (236,621 values; largest relative difference 1.3 × 10⁻¹⁶, otherwise identical): the 118 library, network and example models, the 13 GEKKO models, and psychrolib again with numba. Models random by design were compared seeded. The other 4 are nashpy (no outputs to compare), pyet (the FMU fails), sgp4 (no config) and PyTCI's hand config, which differs only at t = 0, by design ([PyTCI](#pytci)). No config that matched on 2026-10-21 stopped matching. Both runs used Linux (WSL 2, Python 3.13); CGE ran on Windows.

The 5 failures: sgp4, pyet and nashpy (not supported), pymunk and pybamm (no path reaches the result). CGE counts as a success after renaming its `model.py`, NHES with synthetic input data, OpenHENS with a hand-added output and the COIN-OR couenne solver.

---

## Repository examples

| Model | `init` / `init --probe` | Hand config (the repository's `fmugen.toml`) | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| [examples/psychrometry](../examples/psychrometry) (`compute_balances_simplified`) | ✓ | ✓ | ✓ (hand config, 128.7 MB) | 6 outputs. |
| [examples/simple_pid](../examples/simple_pid) (`simple_pid:PID`) | ✓ | ✓ | ✓ (`init --probe` config, 128.7 MB) |  |
| [examples/rc_building](../examples/rc_building) (`Zone`) | ✓ | ✓† | ✓† (hand config, 128.7 MB) | †The repo config fixes `step_size = 3600`, so the generic 1 s run is refused (correct); simulated at 3600 s steps, plain and compiled give the same values. |
| [examples/kalman](../examples/kalman) (`filterpy.kalman:KalmanFilter`; repo config FMI 3: structural parameters, clock) | ✗ no useful outputs | ✓ | ✓ (hand config, rebuilt 2026-10-13) | The `init` configs output only filter settings and likelihoods (`dim_x`, …, `alpha`, `likelihood`), not the state estimate. The repository config is driven by `examples/kalman/run.py`. |
| [examples/sampled_pid](../examples/sampled_pid) (`simple_pid:PID`; repo config: clocks) | ✓ | ✓ | ✓ (hand config, 128.7 MB) | 2026-10-21: the repo config driven by `run.py` (clock ticked every 0.1 s, first-order plant) brings the output to 0.78 → 1.0 setpoint. |

---

## Python libraries

Errors such as `y is an array of shape […], not a single value` in the `init` config are expected: `--probe` finds the shape.

| Model | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|
| `ahrs.filters:Madgwick` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `ahrs.filters:Mahony` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `ambiance:Atmosphere` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/ambiance.toml)) | ✗ no useful outputs | The `init` configs output only the inputs (`h`, `check_bounds`): the results are properties returning 1-element arrays. The hand config (2026-10-22) reads `return:temperature.0` and so on: at 1000 m, T 281.651 K, p 89876.28 Pa, ρ 1.11166 kg/m³ = the direct call. |
| `anastruct:SystemElements` | ✓ | — | ✓ (`init --probe` config, 52.5 MB) |  |
| `antropy:perm_entropy` | ✓ | — | ✓ (`init --probe` config, 105.7 MB) |  |
| `astral.sun:elevation` | ✓ | — | ✓ (`init --probe` config, 101.9 MB) |  |
| `astropy.cosmology:FlatLambdaCDM` | ✓ | — | ✓ (`init --probe` config, 37.7 MB) |  |
| `Bio.SeqUtils:gc_fraction` | ✓ | — | ✓ (`init --probe` config, 29.8 MB) |  |
| `blackscholes:BlackScholesCall` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `cantera:Solution` | ✗ no useful outputs | ✓ ([config](#cantera)) | ✗ no useful outputs | Outputs are only solver settings (`rtol`, `max_steps`): the results are Cython properties, and the gas state can't be set from inputs. |
| `chemicals.vapor_pressure:Antoine` | ✓ | — | ✓ (`init --probe` config, 134.6 MB) |  |
| `colour.temperature:CCT_to_xy_CIE_D` | ✓ | — | ✓ (`init --probe` config, 113.1 MB) |  |
| `commpy.modulation:QAMModem` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/commpy.toml)) | ✗ no useful outputs | `init`: only `m = 4`; the modulated symbols are complex, so they're left out. The hand config (2026-10-22) reads `return:0.real` / `.imag` per symbol: −1 + 1j and 1 − 1j = the direct call. |
| `control:StateSpace` | ✓ | — | ✓ (`init --probe` config, 2026-10-13) | y = (0, −2) = A·x with `--start x=[1.0, 0.0] --start u=[0.0]`. |
| `CoolProp.CoolProp:PropsSI` | ✗ build fails | ✓ ([config](models.md#positional-only-arguments)) | ✗ build fails (`init --probe` config) | C extension with no signature: no variables inferred. |
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
| `heartpy:process` | ✓ | — | ✓ (`init --probe` config, 2026-10-13) | **Needs `setuptools<81` installed by hand** (heartpy imports `pkg_resources` without declaring it). With its `data/data.csv` given by full path: 20 variables, bpm 58.9. |
| `highway_env.envs.highway_env:HighwayEnv` | ✓ | — | ✓ (`init --probe` config, 135.8 MB) |  |
| `hplib.hplib:HeatPump` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `ht.conv_internal:Nu_conv_internal` | ✓ | — | ✓ (`init --probe` config, 134.1 MB) |  |
| `ht.hx:effectiveness_from_NTU` | ✓ | — | ✓ (`init --probe` config, 134.1 MB) |  |
| `iapws.iapws97:_TSat_P` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `iapws:IAPWS97` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `impedance.models.circuits:Randles` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/impedance.toml)) | ✗ no useful outputs | `init`: outputs only echo `initial_guess`; the complex prediction is left out. The hand config (2026-10-22) reads `return:<i>.real` / `.imag` at each frequency: Z(1 Hz) = 0.015019771 − 3.578×10⁻⁵ j Ω = the direct call. |
| `joblib:load` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) | **Compiled: needs `scikit-learn` added to `[model] requirements` by hand**: the model is unpickled, so nothing imports scikit-learn by name. Uncompiled, it needs nothing extra. |
| `librosa:hz_to_mel` | ✓ | — | ✓ (`init --probe` config, 108.5 MB) |  |
| `mendeleev:element` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) | `init --probe`: 79 variables; Fe gives atomic_number 26, atomic_weight 55.845. |
| `mesa.examples:BoltzmannWealth` | ✓ | — | ✓ (`init --probe` config, 111.4 MB) |  |
| `meteocalc:heat_index` | ✓ | — | ✓ (`init --probe` config, 24.6 MB) |  |
| `metpy.calc:dewpoint_from_relative_humidity` | ✗ simulate fails | ✓ ([config](#metpy)) | ✗ simulate fails (`init --probe` config, 111.0 MB) | ValueError: This function changed in version(s) ['1.0']--double check that the function is being called properly. |
| `nashpy:Game` | ✗ simulate fails | — | — | 0.0.43 has no `is_zero_sum`; with `support_enumeration` the method returns a generator: `--probe` finds no outputs, the `init` config fails (`float() argument must be … not 'generator'`). Unchanged 2026-10-22. |
| `neurokit2:ecg_simulate` | ✓ | — | ✓ (`init --probe` config, 114.1 MB) |  |
| `numdifftools:Derivative` | ✓ | — | ✓ (`init --probe` config, 52.3 MB) |  |
| `numpy_financial:pmt` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `obspy.geodetics:gps2dist_azimuth` | ✓ | — | ✓ (`init --probe` config, 77.0 MB) |  |
| `openap:Thrust` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `openturns:Normal` | ✓ | — | ✓ (`init --probe` config, 79.9 MB) |  |
| `pandapower:runpp` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/pandapower.toml), another entry) | ✗ no useful outputs | `runpp(net)` returns None and writes its results onto `net`, which a function entry can't read back. The hand config (2026-10-22) uses `pandapower.contingency:run_contingency(net, nminus1_cases={})`, which runs the same `runpp` and returns the results: 7 bus voltages, 4 line loadings and the transformer loading = `net.res_bus` / `net.res_line` / `net.res_trafo` after `runpp`. |
| `pedon:Genuchten` | ✓ | — | ✓ (`init --probe` config, 83.7 MB) |  |
| `ppigrf:igrf` | ✓ | — | ✓ (`init --probe` config, 101.5 MB) |  |
| `psychrolib:GetHumRatioFromRelHum` | ✓ | — | — | Also with numba installed since 2026-10-21: psychrolib then makes its functions numba ufuncs, which reject keyword arguments, and `init` now passes their arguments by position (`to = "pos:N"`). Both configs = the direct call, with and without numba (psychrolib 2.5.0, numba 0.68.0). |
| pvlib `get_total_irradiance` → `sapm_cell` → `pvwatts_dc` (**composite FMU**) | ✓ (each part) | — | ✓ (2026-10-14) | 2026-10-14: the three parts made with `init --probe`: three weather cases give values identical to calling pvlib in a chain. |
| `pvlib.atmosphere:alt2pres` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.iotools:read_tmy3` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.irradiance:aoi` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.pvsystem:pvwatts_dc` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.solarposition:get_solarposition` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `pvlib.temperature:sapm_cell` | ✓ | — | ✓ (`init --probe` config, 133.0 MB) |  |
| `py_vollib.black_scholes:black_scholes` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `pybamm:Simulation` | ✗ no useful outputs | ✗ simulate fails ([config](match-testing-rerun/configs/pybamm.toml)) | ✗ no useful outputs | Outputs are only solver flags. The voltage is only reachable as `solution["Voltage [V]"]` on the `Solution` that `step()` returns, which isn't a mapping, so a path can't express it (2026-10-22). Needs an fmugen feature: item access by key on objects with `__getitem__`. |
| `PyCO2SYS:sys` | ✓ | — | ✓ (`init --probe` config, 24.8 MB) |  |
| `pyet:pm_fao56` | ✗ simulate fails | — | ✗ simulate fails (`init --probe` config, 111.1 MB) | AttributeError: 'float' object has no attribute 'time' |
| `pyfluids:Fluid` | ✓ | — | ✓ (`init --probe` config, 29.4 MB) |  |
| `pygfunction.heat_transfer:finite_line_source` | ✓ | — | ✓ (`init --probe` config, 52.8 MB) |  |
| `pykalman:KalmanFilter` | ✓ | — | ✓ (`init --probe` config, 52.5 MB) |  |
| `pyloudnorm:Meter` | ✓ | — | ✓ (`init` config, 53.2 MB) | Since 2026-10-21 the `--probe` config simulates too: `blockwise_loudness` (empty until the first call) is skipped at initialization. y and the 17 values = the direct call. |
| `pymap3d:geodetic2enu` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `pymsis:calculate` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `pymunk:Space` | ✗ no useful outputs | ✗ simulate fails ([config](match-testing-rerun/configs/pymunk.toml)) | ✗ no useful outputs | Outputs are only constant settings (`damping`, `collision_slop`, …). A body can be added in `setup`, but `Space.bodies` is a `dict_keys` view, which a path can't index (`'dict_keys' object has no attribute '0'`, 2026-10-22). Needs an fmugen feature: indexing any iterable in a path, or naming an object a `setup` call creates. |
| `pyorbital.astronomy:sun_zenith_angle` | ✓ | — | ✓ (`init --probe` config, 25.0 MB) |  |
| `pyproj:Transformer` | ✓ | — | ✓ (`init --probe` config, 107.9 MB) |  |
| `pyquaternion:Quaternion` | ✓ | — | — | `--call rotate`, axis, angle, vector. Since 2026-10-21 `init --probe` passes axis and angle to the `(*args, **kwargs)` constructor by keyword (it gave them by position: `Unexpected number of elements in sequence`). `rotate` and the quaternion's properties = the direct call. Plain `init` still fails. |
| `pyromat:get` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `pysolar.solar:get_altitude` | ✓ | — | ✓ (`init --probe` config, 101.5 MB) |  |
| `PyTCI.models.propofol:Marsh` | ✗ no useful outputs | ✓ ([config](#pytci)) | ✗ no useful outputs | Outputs only echo the parameters (`weight`, `time_seconds`): the state is in a nested function. Hand config: one dose per step since 2026-10-21; see [PyTCI](#pytci) for what t = 0 shows. |
| `pyteomics.mass:calculate_mass` | ✓ | — | ✓ (`init --probe` config, 28.4 MB) |  |
| `pythermalcomfort.models.jos3:JOS3` | ✓ | ✓ ([config](#jos3)) | ✓ (`init --probe` config, 128.9 MB) | 2026-10-22: a single element can now be read, e.g. `from = "attr:t_core.0"` (the head's core temperature) = element 1 of the whole array = the direct run. |
| `pythermalcomfort.models:pmv_ppd_iso` | ✓ | — | ✓ (`init --probe` config, 97.0 MB) |  |
| `pythermalcomfort.models:sports_heat_stress_risk` | ✓ | — | ✓ (`init --probe` config, 128.9 MB) |  |
| `pywt:dwt` | ✓ | — | ✓ (`init --probe` config, 25.2 MB) |  |
| `pyxirr:npv` | ✓ | — | ✓ (`init --probe` config, 25.0 MB) |  |
| `quantecon:LinearStateSpace` | ✓ | — | ✓ (`init --probe` config, 98.8 MB) |  |
| `QuantLib:blackFormula` | ✓ | — | ✓ (`init --probe` config, 37.2 MB) |  |
| `radioactivedecay:Inventory` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `rainflow:count_cycles` | ✓ | — | ✓ (`init --probe` config, 24.6 MB) |  |
| `rdkit.Chem.Descriptors:MolWt` | ✓ | — | ✓ (`init --probe` config, 44.7 MB) |  |
| `river.linear_model:LinearRegression` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/river.toml)) | ✗ no useful outputs | `init`: only hyperparameters (`l1`, `l2`, …). The hand config (2026-10-22) reads the learned weights (`attr:weights.a`, `attr:weights.b`) and `attr:intercept`: weight a 0.06 → 0.1128 → 0.159264 = the direct run. |
| `roboticstoolbox.models.DH:Panda` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `scipy.signal:lfilter` | ✓ | — | ✓ (`init --probe` config, 53.2 MB) |  |
| `seirsplus.models:SEIRSModel` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/seirsplus.toml)) | ✗ no useful outputs | `init`: outputs only echo the parameters; the state arrays grow each step and are left out. The hand config (2026-10-22) reads the latest counts (`attr:numS.-1`, …) and sets `dt = 0.1`: with `dt` = the step size (1), `run_epoch` keeps only the start point and `t` never advances (the model's own behaviour). S 99900 → 99887.15 → 99874.85 → 99862.85 = the direct run. |
| `sgp4.api:Satrec` | ✗ no config | ✗ not written yet | — | C built-ins with no signature: `--start fr, jd, line1, line2: cannot tell which arguments these are …`. A hand config with `to = "pos:N"` bindings might work. Unchanged 2026-10-22. |
| `shapely:Point` | ✓ | — | ✓ (`init --probe` config, 26.2 MB) |  |
| `simglucose.patient.t1dpatient:T1DPatient` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `simpy:Environment` | ✓ | — | — | `--call run`, no `--start`: `until` is bound to the step's end time (`[time] until = "end_time"`), and `init --probe` gives `now` = 1, 2, 3 = the direct run (2026-10-22). An earlier run failed only because it passed `--start until=1.0`, which makes `until` a fixed input; `init` warns about that. |
| `skfuzzy:interp_membership` | ✓ | — | ✓ (`init --probe` config, 52.3 MB) | **Needs scipy, packaging and networkx installed by hand**: scikit-fuzzy imports them without declaring them. 0.7 = a direct call. |
| `skimage.color:rgb2hsv` | ✓ | — | ✓ (`init --probe` config, 52.8 MB) |  |
| `statsmodels.stats.proportion:proportion_confint` | ✓ | — | ✓ (`init --probe` config, 71.3 MB) |  |
| `tclab:TCLabModel` | ✓ | — | ✓ (`init --probe` config, 128.8 MB) |  |
| `tellurium:loada` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/tellurium.toml)) | ✗ no useful outputs | `init`: only `oneStep`'s return (the time reached). The hand config (2026-10-22) reads the species from the RoadRunner object (`attr:S1`, `attr:S2`): S1 9.9005 → 9.8020 → 9.7045 → 9.6079 = the direct run. `currentTime` is a fixed input there; bind it with `[time] currentTime = "time"` to follow the simulation clock. Needs `LD_LIBRARY_PATH` set to Python's `lib` folder on Linux. |
| `thermo:Chemical` | ✓ | — | ✓ (`init --probe` config, recompiled 2026-10-13) |  |
| `thermofeel:calculate_heat_index_simplified` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `timezonefinder:TimezoneFinder` | ✓ | — | ✓ (`init --probe` config, 58.0 MB) |  |
| `tmm:coh_tmm` | ✓ | — | ✓ (`init --probe` config, 24.6 MB) |  |
| `transforms3d.euler:euler2quat` | ✓ | — | ✓ (`init --probe` config, 24.7 MB) |  |
| `uncertainties:ufloat` | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/uncertainties.toml)) | ✗ no useful outputs | `init`: only `s`, the `ufloat` itself. The hand config (2026-10-22) reads `return:nominal_value` and `return:std_dev`: 1.0 and 0.1. |
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

Dynamic optimization and simulation models built on GEKKO, FMI 2, run on 2026-10-13/14 and checked against each model's published results where it has them. On 2026-10-14 GEKKO's distillation script (nothing to call) was wrapped in a class (first row), and lighter published models (the debutanizer, MPC and FOPDT rows) were added; the last 2 rows are models that only work with extra steps. Every model was rerun and compared with a direct run on 2026-10-22 ([report](match-testing-rerun/report.md)). Only the CFTOC model was compiled: the Nuitka builds were stopped after 30 minutes (see below).

| Model | Source | Entry and `init` options | `init` / `init --probe` | Hand config | Compiled (PyInstaller) | Notes |
|---|---|---|---|---|---|---|
| Distillation column (GEKKO's example, wrapped in a class) | GEKKO [`examples/distillation.py`](https://github.com/BYU-PRISM/GEKKO/blob/master/examples/distillation.py) | `distillation_column.py:DistillationColumn`, `--call step` | ✓ | — | — | Equations unchanged. 7 outputs. At reflux 3.0 the condenser goes 0.785721, 0.837391, 0.867374 and the reboiler 0.190012, 0.145341, 0.120733: the script's own values. |
| Distillation column as a Gym environment | [Kalpesh-RL/DistillationColumn](https://github.com/Kalpesh-RL/DistillationColumn) `f2b9966` | `DistColEnvDynInc_altrewards.py:DistColEnvDynInc`, `--start "Action=[0.0, 0.0, 0.0]" --setup reset` | ✓ | — | — | State, reward, `done` and message change every step; `D`, `B`, `FL` are outputs too. Random by design: D = 1.133 in one run, 1.086 in another. Seeded (`random:seed(0)`, `numpy.random:seed(0)` before construction), the FMU = the direct run (2026-10-22). |
| Batch bioreactor (Monod growth) | [Bartosz1280/Bioreactor-modeling](https://github.com/Bartosz1280/Bioreactor-modeling) `3112aba` | `Bioreactor.py:SimpleBioreactor`, `--call solve`, `time_arr` and `simulation_input` from the repo notebook | ✓ | — | — | 5 outputs (`X`, `S`, `mu`, `dXdt`, `dSdt`) read from the GEKKO variables at the end of the horizon. FMU = the direct run. X goes 0.045100 → 0.045050 → 0.045001 g/L over 3 steps with the notebook's first case (2026-10-22). An earlier run recorded 0.0451 → 0.0444 with starts that weren't written down. |
| Computable general equilibrium economy | [konradarchicinski/cge_model_python](https://github.com/konradarchicinski/cge_model_python) `60d611d` | `Code/model.py:CGE`, `--call results --start capital=0.1 --start labour=0.0` | ✓ | — | — | **Needs its `Code/model.py` renamed** (any other name) **and pandas 2**: `build` refuses a model file named `model.py`, which clashes with UniFMU's backend module. Renamed: 27 outputs, the first step = the direct run (x3 supply 72.076, price 1.119). With pandas 3 the model itself fails (its chained `df[a][b] = …` assignments don't write under copy-on-write). **Windows only**: its data paths are hardcoded with backslashes (`Data\production_structure.csv`). On Linux those are file names containing a backslash, and FMPy refuses an FMU with such names. |
| Constrained finite-time optimal control | [ollyme102b/ros_workspace](https://github.com/ollyme102b/ros_workspace) `03f5938` | `CFTOCSolverV2.py:CFTOCSolverV2`, `--call calculate_optimal_actuation`, the repo test's values | ✗ no config | ✓ ([config](match-testing-rerun/configs/gk_cftoc.toml)) | ✓ (`init --probe` config, 43 MB, 2 min) | **`init` stops** on `--start calculate_optimal_actuation_x0=call:…` (an fmugen bug, see [Known problems](#known-problems)). The hand config passes every argument as a constant, with the repo test's values (A = I, B = 0.5 I, x0 = (1, 0, 0), N = 50, umax = 0.2): FMU = the direct run, y = (−1.7×10⁻⁷, −7.7×10⁻⁴, 0) (2026-10-22). An earlier run recorded y = (−0.09546, −0.02481, 0) with starts that weren't written down. |
| Debutanizer column, steady state (30 stages) | [Arushan45/Debutanizer-Project](https://github.com/Arushan45/Debutanizer-Project) `f6fe813` | `debutanizer.model:solve_steady_state`, `--start reflux_ratio=2.5 --start alpha=1.9717789099` | ✓ | — | — | C4 0.96999957519, vapor 133.0 kmol/h, duty 0.84972 MW: the repo's `results/summary.json` to all digits. **The repository must be installed** (`pip install -e .`): the entry is a package imported by name, which `init` finds only because it runs in the repository folder (see [Known problems](#known-problems)). |
| Debutanizer reflux optimization | same | `debutanizer.model:optimize_reflux`, `--start alpha=1.9717789099` | ✓ | — | — | Reflux 2.7602061381, purity 0.991, vapor 142.8878332478: the repo's optimum to all digits. |
| Linear MPC | [dhruvhaldar/apsis](https://github.com/dhruvhaldar/apsis) `a171cf1` | `apsis/mpc.py:solve_mpc`, the app's defaults | ✓ | — | — | (time, states, inputs) over the horizon: 21 + 42 + 21 outputs. |
| 2×2 FOPDT process (a `GEKKO` subclass) | [BYU-PRISM/Transformer_MPC](https://github.com/BYU-PRISM/Transformer_MPC) `7686735` | `process_fopdt.py:ProcessModel`, `--call run --start "u=[1.0, 0.5]"` | ✓ | — | — | y = (0.3333, 0.0833), (0.6111, 0.1528), (0.8426, 0.2106): K₁₁ = 2, K₂₂ = 1, τ = 5. |
| MPC controller for that process (a `GEKKO` subclass) | same repo | `mpc_gekko.py:MPCModel`, `--call solve` | ✓ | — | — | Runs, but with no setpoints its moves stay near 0. The setpoints are attributes (`y1.SP`): bind an input with `to = "attr:y1.SP"` by hand. |
| Ethanol fed-batch bioreactor (APMonitor's script, wrapped in a class) | [APMonitor](https://apmonitor.com/do/index.php/Main/EthanolBioreactor) | `ethanol_run.py:EthanolBioreactor`, `--call run`: `run()` holds the script's code up to its `solve()`, unchanged (no plots) | ✓ | — | — | `init --probe` finds 30 GEKKO results. FMU = the script run directly, end of the 37 h batch: Xv 2.9955, Xt 11.1237, S 0.5443, P 72.8812 g/L, T 35.4157 °C, Vl 1485 L. The script's model can only be solved once (a second `solve()` fails with `Solution Not Found`, also without fmugen), so `run()` builds it again each step, as running the script does. |
| Nuclear-renewable hybrid energy system | [BYU-PRISM/NHES-opt-sensitivity](https://github.com/BYU-PRISM/NHES-opt-sensitivity) `5e9a6f2` | `simple_nhes.py:model`, `--probe --start "params=call:simple_nhes:nom_params"` | ✓ | — | — | **Run on synthetic data**: the input file `grid_data/more_data_scaled.csv` isn't published. It only needs hourly `Load`, `Wind` and `Solar` in MW, so a 500-hour series is generated (load 400 ± 60 MW daily cycle, daytime solar up to 150 MW, wind around 110 MW). `init --probe` copies the file into the FMU (`cwd`). FMU = the direct run on the same data. The result depends on the series: LCOE 56.134985404 $/MWh on 2026-10-21, 52.372103389 $/MWh on 2026-10-22 with a newly generated one. Also needs seaborn and plotly, which it imports without declaring. |
| Heat exchanger network synthesis | [waikato-ahuora-smart-energy-systems/OpenHENS](https://github.com/waikato-ahuora-smart-energy-systems/OpenHENS) `5081bab` | `openhens:OpenHENS`, `--call solve`, the README's options | ✗ no useful outputs | ✓ ([config](match-testing-rerun/configs/gk_openhens.toml): one output added, `TAC = { from = "attr:_best_solns.0.case.TAC" }`) | — | **Needs the COIN-OR `couenne` executable on PATH**, as its README says (from the [IDAES solver bundle](https://github.com/IDAES/idaes-ext/releases/tag/3.4.2)), and **the repository installed** (`pip install -e .`, as its README also says; see the debutanizer). `init --probe` solves it but finds no outputs: the solutions are kept in a private list. With TAC added by hand, the FMU gives 154853.8586 = the direct run from the same files. Run in the repository itself it gives 159038.72: it also reads the solutions published in its `output_folder`, which `init` doesn't copy into the FMU. About 60 s per step on Windows, 7 s on Linux. |

**Compiling GEKKO models:** with PyInstaller, a GEKKO model compiles in 2 min (43 MB) in a venv with only gekko, numpy, fmugen, PyInstaller and FMPy. In a shared venv with many other packages, the same compile took 19 min and made a 195 MB FMU: fmugen collects every gekko submodule, and some of them import scikit-learn, Pyomo and IPython when installed. **Compile a model in a venv with only what it needs.** Nuitka builds with gekko and numpy took over 30 minutes and were stopped; `examples/simple_pid` compiles with Nuitka and simulates (12 min).

---

## Hand configs

Configs written by hand where `init` can't infer everything. They are linked from the **Hand config** column; all were checked against a direct run on 2026-10-22. The ones added that day are in [match-testing-rerun/configs](match-testing-rerun/configs/), each with a comment saying what it changes and why. `PropsSI`'s is [shown in models.md](models.md#positional-only-arguments).

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

The model advances by `time_seconds`, not by the FMI step size. `give_drug` adds a bolus each time it's called, and a `to = "call:…"` setter runs once per step: 60 steps give 60 doses (61 before 2026-10-21, when initialization's call was repeated by the first step).

The first dose is given at initialization, so the outputs at t = 0 already include it: x1 = 2 mg / (0.228 L/kg × 70 kg) = 0.1253. The first step doesn't give it again. A loop that gives each dose at the start of its step (`give_drug(dose); wait_time(1)`) shows x1 = 0 at t = 0; from t = 1 the two are equal (2026-10-22).

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
- **Module-level scripts can't be models**: a script that solves at import time has nothing to call (GEKKO's distillation example, the ethanol bioreactor). Wrapping its code in a class works.
- **Windows long paths:** cantera and pybamm failed to import from a venv in a deeply nested folder. The FMU runs with the build venv, so deeply nested project folders may hit this.
- **`--start NAME=call:…` is refused for a step method's argument given by its prefixed name** (`calculate_optimal_actuation_x0=call:…`, CFTOC): `--start names that are not arguments of the model`. The documented example `--start decay_units=call:builtins:str('y')` (radioactivedecay) fails the same way, and so does `--convert` with such a name. A `call:` start becomes a constant under the argument's own name, so the check for unused starts doesn't match it. Not a recent regression: the commit before 2026-10-21 fails the same way.
- **A local package imported by name isn't put in the FMU.** An entry like `debutanizer.model:solve_steady_state` or `openhens:OpenHENS`, from a cloned repository that isn't installed, is found by `init` only because it runs in that folder. The FMU's backend runs elsewhere and fails to import it. Installing the repository (`pip install -e .`) works; `init` gives no warning. Packages installed from PyPI aren't affected.
- **Files the model reads from a folder it computes aren't put in the FMU.** `init` copies the files the code or the starts name by a path. OpenHENS also reads saved solutions from its `output_folder`, so its FMU gives a different TAC than running it in the repository (154853.86 against 159038.72).
- **A path can't index a `dict_keys` view** (pymunk's `Space.bodies`) **or read an item by key from an object that isn't a mapping** (pybamm's `solution["Voltage [V]"]`).

Limitations (not bugs):

- **An output's size can't change during the simulation.** FMI variables have fixed sizes (FMI 3 arrays resize only through structural parameters), so an output that becomes `None` or changes length fails the step instead of giving wrong values. `init --probe` comments out the ones it sees change.
- **Model files named `model.py`** are refused by `build`: the name clashes with UniFMU's backend module. Rename the file; `init` warns about it.

Fixed (2026-10-21):

- `attr:` paths index numpy arrays (`from = "attr:t_core.0"`, `"…-1"`), not only lists and tuples.
- ufuncs (numba `@vectorize`, psychrolib with numba) get their arguments by position.
- `init` warns about a model file named `model.py`.
- Methods written without `self`, to be called on the class (`Model.building(df, …)`): `init` detects them and writes `[model] call_on_class = true`, so the runtime calls `Model.building(…)` and the first argument is kept as an input instead of being dropped as `self`.
- `to = "call:…"` setters run once per model call: the first step skips the call when the value hasn't changed since initialization ran it, and integration stages don't repeat it. [PyTCI](#pytci): 60 steps give 60 doses, and x1, x2, x3, xeo = the model called directly.
- A `(*args, **kwargs)` constructor that needs its `--start` values as keywords (pyquaternion's `Quaternion(axis=…, angle=…)`) gets them so with `--probe`; before, they always went by position. (The old entry said the step's values went to the constructor; they didn't: `vector` already went to `rotate`.) Without `--probe` they still go by position, as `StateSpace(A, B, C, D)` needs.
- An array output that has the wrong size before the first step (pyloudnorm's `blockwise_loudness`, empty until the first call) is skipped at initialization instead of failing it; steps still check the size. The pyloudnorm `--probe` config now simulates and matches the direct call.
- Not bugs after all: `init` does write `[model] requirements` (pinned to the installed versions), and simpy's `until` is bound to the step's end time unless `--start until=…` makes it a fixed input, which `init` warns about.

---

## Deployment with Liqo

On 2026-10-07, about 50 of the library models (numpy_financial, QuantLib, pymap3d, shapely, librosa, mendeleev, tellurium, …) were also deployed across two kind clusters peered with Liqo v1.2.0. Each model's best config got `[model] requirements` and was built into an image with `docker/Dockerfile` (`MODEL=docker/models/r3/<name>`), then run as a Job on the virtual node `fmu-remote`, talking to the OPC UA server in `fmu-local` through the reflected Service. The configs are in `docker/models/r3/<name>/fmugen.toml`.

**Liqo itself caused no failures**: runs succeeded on `fmu-remote` exactly where they succeeded on Windows, with the same values. Exceptions: tellurium's Linux image lacked a dependency (`No module named 'tesbml'`), and antropy's run hung after connecting (cause not investigated). Class models showed `0` in the first row of the runner's CSV (t = 0), and the right value from t = 1.

---

## Versions

The latest on PyPI for Python 3.13 at the time of each run (2026-10-06 to 2026-10-14). Pinned where it mattered: pandas 2.3.3 for the CGE model, `setuptools<81` for heartpy.

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
