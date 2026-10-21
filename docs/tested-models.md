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

**FMI 2 by default.** A model was run with FMI 3 only when no FMI 2 config simulated ("2 → 3" in the tables). Errors were recorded first and fixed afterwards; rows show the result after the fixes, with the date when it is later than the main run.

Setup: Windows 11, Python 3.13, `uv` venvs, fmugen editable from this checkout, FMPy 0.3.32, PyInstaller 6.22.3, UniFMU 0.14. The library and neural-network models were run on 2026-10-09 at `0e0b670`, with fixes and reruns up to 2026-10-13; the GEKKO models on 2026-10-13 and 2026-10-14 (gekko 1.3.2, local solver).

Columns: **init / init --probe**: config written. **build + simulate**: per config (`plain` = code-only, `probe`, `repo` = the committed config). **compiled**: the config compiled with PyInstaller, and the result. **Notes**: the first error, or what was checked.

---

## Summary

Libraries, neural networks and repository examples (116 `init` runs; the 2 FMI 3 examples have no `init` run):

| | Count |
|---|---|
| `init` writes a config | 111 |
| `init --probe` writes a config | 115 |
| **Simulate correctly with FMI 2** (at least one config) | **108** |
| Pass only with FMI 3 | 0 |
| Fail with FMI 2 and FMI 3 | 10 |
| **Compiled FMU simulates** | **108**: every model that simulates uncompiled |

The code-only config is enough for about 60 % of models. The rest return arrays, tuples, strings or objects, which only `--probe` types correctly; the error message points to it.

The 10 failures: `PropsSI` and sgp4 (C built-ins with no signature: hand config needed), `fluids.units` ×2 and metpy (pint quantities: hand config needed), pyet (needs pandas Series), psychrolib (a numba ufunc takes no keyword arguments), simpy (`until` not bound to time), pyquaternion (`*args` constructor gets the step's arguments), nashpy (the method returns a generator).

GEKKO: 10 of 16 simulate correctly (CGE once its `model.py` is renamed). The other 6 fail for reasons of their own: two can't be called or crash without fmugen, and four need inputs, data or solvers that aren't available.

---

## Repository examples

| Model | FMI | init | init --probe | build + simulate (per config) | compiled (PyInstaller) + simulate | Notes |
|---|---|---|---|---|---|---|
| [examples/psychrometry](../examples/psychrometry) (`compute_balances_simplified`) | 2 | ✓ | ✓ | plain ✓ / probe ✓ / repo ✓ | repo: ✓, 128.7 MB | 6 outputs. `init -o` outside the model's folder now stops with a `fmugen: error` naming where to write the config. |
| [examples/simple_pid](../examples/simple_pid) (`simple_pid:PID`) | 2 | ✓ | ✓ | plain ✓ / probe ✓ / repo ✓ | probe: ✓, 128.7 MB |  |
| [examples/rc_building](../examples/rc_building) (`Zone`) | 2 | ✓ | ✓ | plain ✓ / probe ✓ / repo ✓† | repo: ✓†, 128.7 MB | †The repo config fixes `step_size = 3600`, so the generic 1 s run is refused (correct); simulated at 3600 s steps, plain and compiled give the same values. |
| [examples/kalman](../examples/kalman) (`filterpy.kalman:KalmanFilter`; repo config FMI 3: structural parameters, clock) | 2 / 3 | ✓ | ✓ | plain ✓ / probe ✓ (FMI 2) / repo ✓ | repo: ✓ (rebuilt 2026-10-13) | Plain and probe: the `filterpy.kalman:KalmanFilter` FMI 2 configs simulate. The repo config fails the generic run (the clock is never ticked); `examples/kalman/run.py` runs it correctly, compiled too. |
| [examples/sampled_pid](../examples/sampled_pid) (FMI 3: clocks) | 3 | — | — | repo ✓ | repo: ✓, 128.7 MB |  |

---

## Python libraries

Errors such as `y is an array of shape […], not a single value` in the code-only config are expected: `--probe` finds the shape.

| Model | FMI | init | init --probe | build + simulate (per config) | compiled (PyInstaller) + simulate | Notes |
|---|---|---|---|---|---|---|
| `ahrs.filters:Madgwick` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `ahrs.filters:Mahony` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | TypeError: b is an array of shape [3], not a single value: give it dimensions = [3] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `ambiance:Atmosphere` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |
| `anastruct:SystemElements` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 52.5 MB | TypeError: buckling_factor is None |
| `antropy:perm_entropy` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 105.7 MB |  |
| `astral.sun:elevation` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.9 MB |  |
| `astropy.cosmology:FlatLambdaCDM` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 37.7 MB |  |
| `Bio.SeqUtils:gc_fraction` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 29.8 MB |  |
| `blackscholes:BlackScholesCall` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.7 MB |  |
| `cantera:Solution` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `chaospy:Normal` | — | — | — | — | — | Not installable on Windows / Python 3.13 (2026-10-07): its dependency `numpoly` has no wheel and needs MSVC. Replaced by openturns. |
| `chemicals.vapor_pressure:Antoine` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 134.6 MB |  |
| `colour.temperature:CCT_to_xy_CIE_D` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 113.1 MB | TypeError: y is an array of shape [2], not a single value: give it dimensions = [2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `commpy.modulation:QAMModem` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 78.2 MB | TypeError: y is an array of shape [2], not a single value: give it dimensions = [2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `control:StateSpace` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (2026-10-13) | y = (0, −2) = A·x with `--start x=[1.0, 0.0] --start u=[0.0]`. Code-only: the array result is assumed a single Real. |
| `CoolProp.CoolProp:PropsSI` | 2 → 3 | ✓ | ✓ | plain ✗ / probe ✗ | probe: ✗ | C extension with no signature: no variables inferred. Needs a hand config ([below](#hand-configs)). |
| `cv2:KalmanFilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 66.3 MB |  |
| `dysts:Lorenz` (`call = "rhs"`, `[model] integrate`) | 2, 3 | — | — | ✓ | — | 2026-10-14: dysts 0.96's `Lorenz().rhs(X, t)` integrated by the FMU, 20 steps of 0.05 s, against `solve_ivp` at 1e-11: largest difference 1.3 × 10⁻⁶ with `"scipy:DOP853"` (FMI 3) and 3.3 × 10⁻⁸ with `"rk4"`, 50 substeps (FMI 2). |
| `electricpy:powerset` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 71.2 MB |  |
| `erfa:gmst06` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.8 MB |  |
| `filterpy.common:Q_discrete_white_noise` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 128.8 MB | TypeError: y is an array of shape [2, 2], not a single value: give it dimensions = [2, 2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `filterpy.gh:GHFilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.8 MB |  |
| `fluids.core:Reynolds` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.8 MB |  |
| `fluids.friction:friction_factor` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.8 MB |  |
| `fluids.units:head_from_P` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 133.8 MB | FMI 2: TypeError: 100000.0 has no quantity — FMI 3: TypeError: 100000.0 has no quantity |
| `fluids.units:Reynolds` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 133.8 MB | FMI 2: TypeError: 1.0 has no quantity — FMI 3: TypeError: 1.0 has no quantity |
| `gsw:rho` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 103.3 MB |  |
| `gymnasium.envs.classic_control.cartpole:CartPoleEnv` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 135.6 MB | ValueError: 147626572821865577400907706530850663577 is out of range for Integer |
| `gymnasium.envs.classic_control.pendulum:PendulumEnv` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 135.6 MB | ValueError: 172939238529957257140098871392319507192 is out of range for Integer |
| `haversine:haversine` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.6 MB |  |
| `heartpy:process` | 2 | ✓ | ✓ | probe ✓ | probe: ✓ (2026-10-13) | With its `data/data.csv` given by full path: 20 variables, bpm 58.9 (compiled too). Imports `pkg_resources`: needs `setuptools<81`. |
| `highway_env.envs.highway_env:HighwayEnv` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 135.8 MB | TypeError: y0 is an array of shape [5, 5], not a single value: give it dimensions = [5, 5] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `hplib.hplib:HeatPump` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `ht.conv_internal:Nu_conv_internal` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 134.1 MB |  |
| `ht.hx:effectiveness_from_NTU` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 134.1 MB |  |
| `iapws.iapws97:_TSat_P` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | 2026-10-14: with `discard_on = ["builtins:NotImplementedError"]`, a step at 30 MPa returns `discard`; the output keeps 453.04 K, and the step retried at 2 MPa succeeds (485.53 K). |
| `iapws:IAPWS97` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | TypeError: float() argument must be a string or a real number, not 'dict' |
| `impedance.models.circuits:Randles` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 103.7 MB | TypeError: y is an array of shape [4], not a single value: give it dimensions = [4] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `joblib:load` | 2 | ✗ | ✓ | probe ✓ | probe: ✓ (recompiled 2026-10-13) | fmugen: error: --start names that are not arguments of the model: ['X'] |
| `librosa:hz_to_mel` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 108.5 MB |  |
| `mendeleev:element` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | `--probe`: 79 variables; Fe gives atomic_number 26, atomic_weight 55.845. |
| `mesa.examples:BoltzmannWealth` | 2 | ✓ | ✓ | plain ✗ / probe ✓ | probe: ✓, 111.4 MB | fmugen: error: the config defines no FMU variables: add [inputs]/[parameters] and [outputs] (the model's arguments and results could not be inferred) |
| `meteocalc:heat_index` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.6 MB |  |
| `metpy.calc:dewpoint_from_relative_humidity` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 111.0 MB | FMI 2: ValueError: This function changed in version(s) ['1.0']--double check that the function is being called properly. — FMI 3: ValueError: This function changed in version(s) ['1.0']--double check that the function is being called properly. |
| `nashpy:Game` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe: no outputs | — | 0.0.43 has no `is_zero_sum`; with `support_enumeration` the method returns a generator: `--probe` finds no outputs, the code-only config fails (`float() argument must be … not 'generator'`). |
| `neurokit2:ecg_simulate` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 114.1 MB | TypeError: y is an array of shape [100], not a single value: give it dimensions = [100] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `numdifftools:Derivative` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.3 MB |  |
| `numpy_financial:pmt` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.7 MB |  |
| `obspy.geodetics:gps2dist_azimuth` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 77.0 MB |  |
| `openap:Thrust` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `openturns:Normal` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 79.9 MB | TypeError: Wrong number or type of arguments for overloaded function 'new_Normal'. |
| `pandapower:runpp` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 127.9 MB |  |
| `pedon:Genuchten` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 83.7 MB |  |
| `ppigrf:igrf` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |
| `psychrolib:GetHumRatioFromRelHum` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 128.7 MB | FMI 2: OSError('exception: access violation reading 0x00000000000009AA') — FMI 3: TypeError: unexpected keyword arguments to ufunc: 'Pressure', 'RelHum', 'TDryBulb' |
| pvlib `get_total_irradiance` → `sapm_cell` → `pvwatts_dc` (**composite FMU**) | 2, 3 | ✓ (each part) | ✓ (each part) | ✓ | ✓ (2026-10-14) | 2026-10-14: the three parts made with `init --probe`, built with `--compile pyinstaller`: the FMU holds no `.py` file, and three weather cases give values identical to calling pvlib in a chain. |
| `pvlib.atmosphere:alt2pres` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.0 MB |  |
| `pvlib.iotools:read_tmy3` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 133.0 MB | TypeError: float() argument must be a string or a real number, not 'DataFrame' |
| `pvlib.irradiance:aoi` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 133.0 MB | Exception('Failed to instantiate model') |
| `pvlib.pvsystem:pvwatts_dc` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.0 MB |  |
| `pvlib.solarposition:get_solarposition` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 133.0 MB | TypeError: float() argument must be a string or a real number, not 'DataFrame' |
| `pvlib.temperature:sapm_cell` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.0 MB |  |
| `py_vollib.black_scholes:black_scholes` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `pybamm:Simulation` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | TypeError: float() argument must be a string or a real number, not 'Solution' |
| `PyCO2SYS:sys` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.8 MB | TypeError: float() argument must be a string or a real number, not 'dict' |
| `pyet:pm_fao56` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 111.1 MB | FMI 2: AttributeError: 'float' object has no attribute 'time' — FMI 3: AttributeError: 'float' object has no attribute 'time' |
| `pyfluids:Fluid` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 29.4 MB | ValueError: Invalid or not defined state! |
| `pygfunction.heat_transfer:finite_line_source` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.8 MB |  |
| `pykalman:KalmanFilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.5 MB |  |
| `pyloudnorm:Meter` | 2 | ✓ | ✓ | plain ✓ / probe build ✓, sim ✗ | plain: ✓, 53.2 MB | ValueError: blockwise_loudness has 0 values, expected 17 |
| `pymap3d:geodetic2enu` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.7 MB | TypeError: y is a tuple of shape [3], not a single value: give it dimensions = [3] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pymsis:calculate` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `pymunk:Space` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 26.3 MB |  |
| `pyorbital.astronomy:sun_zenith_angle` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 25.0 MB |  |
| `pyproj:Transformer` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 107.9 MB | TypeError: y is a tuple of shape [2], not a single value: give it dimensions = [2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pyquaternion:Quaternion` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 24.6 MB | FMI 2: ValueError: Unexpected number of elements in sequence. Got: 2, Expected: 4. — FMI 3: ValueError: Unexpected number of elements in sequence. Got: 2, Expected: 4. |
| `pyromat:get` | 2 | ✗ | ✓ | probe ✓ | probe: ✓ (recompiled 2026-10-13) | fmugen: error: --start names that are not arguments of the model: ['T'] |
| `pysolar.solar:get_altitude` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 101.5 MB | pysolar.tzinfo_check.NoTimeZoneInfoError: datetime value '2026-10-09 00:00:00' given for arg 'when' should be made timezone-aware. |
| `PyTCI.models.propofol:Marsh` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |
| `pyteomics.mass:calculate_mass` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 28.4 MB |  |
| `pythermalcomfort.models.jos3:JOS3` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.9 MB |  |
| `pythermalcomfort.models:pmv_ppd_iso` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 97.0 MB | TypeError: tsv is a string ('Neutral'), not a Real: set type = "String" for it in the config |
| `pythermalcomfort.models:sports_heat_stress_risk` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 128.9 MB | ValueError: could not convert string to float: 'Increase frequency and/or duration of rest breaks' |
| `pywt:dwt` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 25.2 MB | TypeError: y0 is an array of shape [9], not a single value: give it dimensions = [9] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pyxirr:npv` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 25.0 MB |  |
| `quantecon:LinearStateSpace` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 98.8 MB |  |
| `QuantLib:blackFormula` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 37.2 MB |  |
| `radioactivedecay:Inventory` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | TypeError: float() argument must be a string or a real number, not 'Inventory' |
| `rainflow:count_cycles` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.6 MB | TypeError: y is a list of shape [4], not a single value: give it dimensions = [4] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `rdkit.Chem.Descriptors:MolWt` | 2 | ✓ | ✓ | plain ✗ / probe ✓ | probe: ✓, 44.7 MB | fmugen: error: the config defines no FMU variables: add [inputs]/[parameters] and [outputs] (the model's arguments and results could not be inferred) |
| `river.linear_model:LinearRegression` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 102.9 MB | LookupError: max_cum_l1: cannot read attribute 'max_cum_l1' (AttributeError("'LinearRegression' object has no attribute 'max_cum_l1'")) |
| `roboticstoolbox.models.DH:Panda` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | TypeError: float() argument must be a string or a real number, not 'SE3' |
| `scipy.signal:lfilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 53.2 MB |  |
| `seirsplus.models:SEIRSModel` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 111.2 MB |  |
| `sgp4.api:Satrec` | 2 → 3 | ✗ | ✗ |  | — | C built-ins with no signature: `--start fr, jd, line1, line2: cannot tell which arguments these are …`. Needs a hand config. |
| `shapely:Point` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 26.2 MB |  |
| `simglucose.patient.t1dpatient:T1DPatient` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `simpy:Environment` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 24.7 MB | FMI 2: ValueError: until (1.0) must be greater than the current simulation time — FMI 3: ValueError: until (1.0) must be greater than the current simulation time |
| `skfuzzy:interp_membership` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.3 MB |  |
| `skimage.color:rgb2hsv` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.8 MB |  |
| `statsmodels.stats.proportion:proportion_confint` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 71.3 MB |  |
| `tclab:TCLabModel` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.8 MB |  |
| `tellurium:loada` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `thermo:Chemical` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | TypeError: CAS is a string ('7732-18-5'), not a Real: set type = "String" for it in the config |
| `thermofeel:calculate_heat_index_simplified` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.7 MB | ValueError: Calling nonzero on 0d arrays is not allowed. Use np.atleast_1d(scalar).nonzero() instead. If the context of this error is of the form `arr[nonzero(cond)]`, just use `arr[cond]`. |
| `timezonefinder:TimezoneFinder` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 58.0 MB |  |
| `tmm:coh_tmm` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.6 MB | TypeError: kz_list is an array of shape [3], not a single value: give it dimensions = [3] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `transforms3d.euler:euler2quat` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.7 MB |  |
| `uncertainties:ufloat` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.7 MB | TypeError: can't convert an affine function (<class 'uncertainties.core.Variable'>) to float; use x.nominal_value |
| `windpowerlib.wind_speed:logarithmic_profile` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |

---

## Neural networks

Each was installed as published (`pip install <package>`) into its own venv together with fmugen. Neural networks need `--probe`: their result sizes depend on the weights, and their code is mostly compiled or framework code. Weights from Hugging Face are downloaded on first use, unless the FMU is built with `--hf-weights` (automatic with `--vendor` / `--compile`). `--capture-output` is needed whenever a model prints while loading, which hangs UniFMU 0.14 otherwise.

| Model | FMI | init | init --probe | build + simulate (per config) | compiled (PyInstaller) + simulate | Notes |
|---|---|---|---|---|---|---|
| `chronos:ChronosBoltPipeline` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 322.8 MB |  |
| `silero_vad:load_silero_vad` | 2 | ✗ | ✓ | probe ✓ | probe: ✓ (recompiled 2026-10-13) | fmugen: error: --start names that are not arguments of the model: ['sr', 'x'] |
| `tsfm_public.toolkit.get_model:get_model` | 2 | ✗ | ✓ | probe ✓ | probe: ✓ (recompiled 2026-10-13) | fmugen: error: --start names that are not arguments of the model: ['past_values'] |
| `stable_baselines3:PPO` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓ (recompiled 2026-10-13) |  |
| `surfaces.test_functions.machine_learning.hyperparameter_optimization.tabular.regression.test_functions.gradient_boosting_regressor:GradientBoostingRegressorFunction` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 294 MB (recompiled 2026-10-13) |  |
| `torchani.models:ANI2x` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓ (recompiled 2026-10-13) | TypeError: species is an array of shape [1, 5], not a single value: give it dimensions = [1, 5] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |

---

## GEKKO models

Dynamic optimization and simulation models built on GEKKO, FMI 2. The last 6 rows fail for reasons of their own; on 2026-10-14 the distillation script was reworked into a class (first row) and the others were complemented by lighter published models (the debutanizer, MPC and FOPDT rows).

| Model | Source | Entry and `init` options | init | init --probe | build + simulate (FMI 2) | Notes |
|---|---|---|---|---|---|---|
| Distillation column (GEKKO's example, reworked into a class; equations unchanged) | GEKKO [`examples/distillation.py`](https://github.com/BYU-PRISM/GEKKO/blob/master/examples/distillation.py) | `distillation_column.py:DistillationColumn`, `--call step` | ✓ | ✓ | plain ✓ / probe ✓ | 7 outputs. At reflux 3.0 the condenser goes 0.785721, 0.837391, 0.867374 and the reboiler 0.190012, 0.145341, 0.120733: the script's own values. The original module-level script has nothing to call. |
| Distillation column as a Gym environment | [Kalpesh-RL/DistillationColumn](https://github.com/Kalpesh-RL/DistillationColumn) `f2b9966` | `DistColEnvDynInc_altrewards.py:DistColEnvDynInc`, `--start "Action=[0.0, 0.0, 0.0]" --setup reset` | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | State, reward, `done` and message change every step; `D`, `B`, `FL` are outputs too (D = 1.133, B = 0.873). Code-only: `Action` given as one Real. |
| Batch bioreactor (Monod growth) | [Bartosz1280/Bioreactor-modeling](https://github.com/Bartosz1280/Bioreactor-modeling) `3112aba` | `Bioreactor.py:SimpleBioreactor`, `--call solve`, `time_arr` and `simulation_input` from the repo notebook | ✓ | ✓ | probe ✓ | 5 outputs (`X`, `S`, `mu`, `dXdt`, `dSdt`) read from the GEKKO variables at the end of the horizon; X goes 0.0451 → 0.0444 g/L over 3 steps. |
| Computable general equilibrium economy | [konradarchicinski/cge_model_python](https://github.com/konradarchicinski/cge_model_python) `60d611d` | `Code/model.py:CGE`, `--call results --start capital=0.1 --start labour=0.0` | ✓ | ✓ | ✗ unless renamed | `build` refuses a model file named `model.py` (clashes with UniFMU's backend; intended). From a renamed copy: 27 outputs, first step = the direct run (x3 supply 72.076, price 1.119). Needs pandas 2 (with pandas 3 the model itself fails). |
| Constrained finite-time optimal control | [ollyme102b/ros_workspace](https://github.com/ollyme102b/ros_workspace) `03f5938` | `CFTOCSolverV2.py:CFTOCSolverV2`, `--call calculate_optimal_actuation`, the repo test's starts, `--start calculate_optimal_actuation_x0=…` | — | ✓ | probe ✓ | y = (−0.09546, −0.02481, 0), then (−0.09521, −0.02558, 0) twice = the class called directly. `--compile pyinstaller`: ✓, 2 min, 43 MB, same values. `--compile nuitka`: stopped after 30 min. |
| Debutanizer column, steady state (30 stages) | [Arushan45/Debutanizer-Project](https://github.com/Arushan45/Debutanizer-Project) `f6fe813` | `debutanizer.model:solve_steady_state`, `--start reflux_ratio=2.5 --start alpha=1.9717789099` | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | C4 0.96999957519, vapor 133.0 kmol/h, duty 0.84972 MW: the repo's `results/summary.json` to all digits. Code-only: `c4_profile` is a list. |
| Debutanizer reflux optimization | same | `debutanizer.model:optimize_reflux`, `--start alpha=1.9717789099` | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | Reflux 2.7602061381, purity 0.991, vapor 142.8878332478: the repo's optimum to all digits. |
| Linear MPC | [dhruvhaldar/apsis](https://github.com/dhruvhaldar/apsis) `a171cf1` | `apsis/mpc.py:solve_mpc`, the app's defaults | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | (time, states, inputs) over the horizon: 21 + 42 + 21 outputs. |
| 2×2 FOPDT process (a `GEKKO` subclass) | [BYU-PRISM/Transformer_MPC](https://github.com/BYU-PRISM/Transformer_MPC) `7686735` | `process_fopdt.py:ProcessModel`, `--call run --start "u=[1.0, 0.5]"` | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | y = (0.3333, 0.0833), (0.6111, 0.1528), (0.8426, 0.2106): K₁₁ = 2, K₂₂ = 1, τ = 5. Outputs list only the GEKKO variables, not GEKKO's own state (fixed 2026-10-14). |
| MPC controller for that process (a `GEKKO` subclass) | same repo | `mpc_gekko.py:MPCModel`, `--call solve` | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | Runs, but with no setpoints its moves stay near 0. The setpoints are attributes (`y1.SP`): bind an input with `to = "attr:y1.SP"` by hand. |
| Ethanol fed-batch bioreactor | [APMonitor](https://apmonitor.com/do/index.php/Main/EthanolBioreactor) | `ethanol_bioreactor.py` | ✗ | ✗ | — | A script: importing it runs its own solve, and GEKKO's local solver crashes (`Access Violation … ace.f90`), also when run directly. **Not fmugen's.** Now shown as a `fmugen: error` naming the line. |
| Cell transmembrane potential | [0xDBFB7/transmembrane_potential](https://github.com/0xDBFB7/transmembrane_potential) `165c86f` | `transmembrane_lib.py:gekko_sim_method`, `--kind function` | ✓ | ✓ | ✗ | `NameError: name 'GEKKO' is not defined`: dead code upstream. **Not fmugen's.** |
| Directional drilling MPC | [Xiang-Gu/CS394R_RL_Directional_Drilling](https://github.com/Xiang-Gu/CS394R_RL_Directional_Drilling) `12a45cf` | `mpc/mpc.py:solveMPC`, `--call action --start "state=[0.0, 0.0, 0.0, 0.0]"` | ✓ | ✓ | ✗ | The constructor takes a Gym environment object, which no FMU input can give; it also solves on APMonitor's server (`remote=True`). |
| Nuclear-renewable hybrid energy system | [BYU-PRISM/NHES-opt-sensitivity](https://github.com/BYU-PRISM/NHES-opt-sensitivity) `5e9a6f2` | `simple_nhes.py:model`, `--start params=<nom_params>` | ✓ | ✓ | ✗ | Reads `grid_data/more_data_scaled.csv`, which isn't published. |
| Residential heat diagnosis | [energietransitie/needforheat-diagnosis-software](https://github.com/energietransitie/needforheat-diagnosis-software) `48d3a85` | `analysis/rhc_analysis.py:Model`, `--call building` | ✓ | ✓ | ✗ | Methods written without `self`, and the input is a pandas DataFrame of measurements, which no FMU input can give. |
| Heat exchanger network synthesis | [waikato-ahuora-smart-energy-systems/OpenHENS](https://github.com/waikato-ahuora-smart-energy-systems/OpenHENS) `5081bab` | `openhens:OpenHENS`, `--call solve`, the README's options | ✓ | ✓ | ✗ | `couenne solver not found`: needs the COIN-OR binaries on PATH. |

**Compiling GEKKO models:** with PyInstaller, a GEKKO model compiles in 2 min (43 MB) in a venv with only gekko, numpy, fmugen, PyInstaller and FMPy. In a shared venv with many other packages, the same compile took 19 min and made a 195 MB FMU: fmugen collects every gekko submodule, and some of them import scikit-learn, Pyomo and IPython when installed. **Compile a model in a venv with only what it needs.** Nuitka builds with gekko and numpy took over 30 minutes and were stopped; `examples/simple_pid` compiles with Nuitka and simulates (12 min).

---

## Hand configs

Some models need a config written by hand, since `init` can't infer it.

- `CoolProp.CoolProp:PropsSI`: [shown in models.md](models.md#positional-only-arguments).
- `fluids.units:Reynolds` / `head_from_P`: `convert = "pint"` and a `unit` on each input; output `unit = "cm"` for `head_from_P`.
- `pythermalcomfort.models.jos3:JOS3`: inputs `to = "attr:tdb"`, …, `setup = ["options.update({'limit_dshiv/dt': True})"]`; `init` writes `globals`.

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
