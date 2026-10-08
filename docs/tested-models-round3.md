# Tested models, round 3: 50 more published models, with Liqo

50 published, unmodified models, each from a library or domain not covered in [tested-models.md](tested-models.md) or [tested-models-round2.md](tested-models-round2.md). Each was run through four steps, all with **FMI 3**:

1. `fmugen init` (code only, no probe)
2. `fmugen init --probe`
3. `fmugen build --capture-output` on each config that `init` wrote, then `fmpy.simulate_fmu` (3 s, 1 s steps) on Windows
4. **Deployment with Liqo across two clusters.** The best config gets `[model] requirements`. The image is built with `docker/Dockerfile` (`MODEL=docker/models/r3/<name>`) and loaded into both kind clusters (`fmu-local`, `fmu-remote`, peered by `docker/liqo/up.sh`). The OPC UA server and UI are set to that image, and a run Job is created in `fmu-sim` the same way the UI creates one, with `liqo.io/type In virtual-node` affinity. It runs `fmu_runner.py` on the virtual node `fmu-remote` for 3 s and talks to the OPC UA server in `fmu-local` through the reflected Service.

Errors were **recorded, not fixed**. No fmugen code was changed. When an error came from my own `init` options (a wrong argument name, a library missing a dependency), I retried with corrected options and say so.

Setup: Windows 11, Python 3.13 venvs made with `uv` (one per model), fmugen from this checkout at `add8efb` (editable), FMPy, UniFMU 0.14.0. For Liqo: kind, Liqo v1.2.0, `python:3.13-slim` images. Date: 2026-10-07. The configs used for deployment are in `docker/models/r3/<name>/fmugen.toml`.

## Summary

| | Count |
|---|---|
| Models tried | 51 (50 installable; chaospy didn't install) |
| `init` (no probe) writes a config | 46 of 50 |
| `init --probe` writes a config | 47 of 50 |
| Best config builds and simulates correctly on Windows | 35 |
| Deployed through Liqo and the run **succeeded on `fmu-remote`** | 33 |
| Run failed on `fmu-remote`, with the same error as on Windows | 8 |
| Image build failed (Linux only) | 1 (tellurium) |
| Run hung on `fmu-remote` | 1 (antropy) |
| Not deployed (`init` or `build` failed) | 7 |

Every model that passed on Windows also passed through Liqo with the same values (spot-checked to all digits), except antropy (hung) and tellurium (image). **Liqo itself caused no failures**: every Job was scheduled on the virtual node `fmu-remote`, reached `opcua-server` through the reflected Service, and the UI's way of reading logs through the virtual node returned the CSV.

Every value marked "= direct" below was compared with a direct call of the library in the same venv.

### Main problems found

1. **`--start NAME=call:…` is refused for `*args` models** with `{'call': '…'} is not an FMI value` (pyquaternion `Quaternion`, rdkit `MolWt`, nashpy `Game`). It works for named arguments (haversine, tmm, pykalman).
2. **`call:` start values can only have literal arguments, and the error is misleading.** `call:numpy:sin(numpy.linspace(0,20,200))` gives `module 'numpy' has no attribute 'linspace(0, 20, 200)'`. `call:numpy:array([float("inf"),…])` gives `cannot import "[float('inf'), …]"`. `call:pyfluids:FluidsList.Water` *calls* the enum member (`'FluidsList' object is not callable`). There's no way to pass a function object (`numdifftools.Derivative(fun=numpy.sin)` calls `sin()`). In every case, `init` only warns that the probe failed and still writes the config, and `build` packages it.
3. **A `{ call = … }` constant that fails at run time kills the backend with no reason shown.** fmpy: `Failed to instantiate FMU … backend exited unexpectedly with exit status 1`, with only the "dispatcher endpoint received" line as output. The Python traceback is lost, even with `debug_logging=True`. Affected: tmm, antropy (first attempts), pyloudnorm, pyfluids, numdifftools, heartpy.
4. **`init` writes configs that `build` rejects** (more cases of round 2's problem 2):
   - **pygfunction** `finite_line_source(time, …)`: the argument named `time` becomes an input. `build`: `FMI 3 reserves the variable name 'time'`. `init` doesn't rename it.
   - **radioactivedecay** `Inventory(…, units='Bq').decay(decay_time, units='s')`: the constructor's and the method's `units` both become variables. `build`: `duplicate variable or clock names: ['units']`.
   - **astropy** `FlatLambdaCDM`: the `Tcmb0` default is an astropy `Parameter` descriptor, which `init` splits into fields like a dataclass (`Tcmb0_derived`, `Tcmb0_doc`, … `to = "arg:Tcmb0.derived"`). `build`: `'Tcmb0' is not an argument of FLRW.age`. Same with and without `--probe` (the probe also failed with `The value must be a valid Python or Numpy numeric type`).
5. **`init` resolves an alias to the wrong function.** `PyCO2SYS:sys` is `PyCO2SYS.engine.nd.CO2SYS`, but `init` writes `entry = "PyCO2SYS:CO2SYS"` (its `__name__`), which is the old MATLAB-style top-level `CO2SYS`, a different function. `build`: `'par1' is not an argument of CO2SYS`.
6. **With an `*args` constructor, the step method's `--start` values go to the constructor too.** openturns `Normal(mu, sigma).computePDF(x)`: `mu, sigma, x: passed by position to *args`, so `Normal(0.0, 1.0, 0.5)` fails (SWIG overload error) in the probe and at initialization.
7. **Non-numeric objects typed Real.** `uncertainties.ufloat` returns an `AffineScalarFunc`. The probe writes `y = { from = "return" }` (Real) without checking that it converts, and initialization fails with `can't convert an affine function … to float`. `init` doesn't suggest `nominal_value` / `std_dev`.
8. **Without `--probe`, array or tuple results are written as scalar Reals, and the run fails** with `only 0-dimensional arrays can be converted to Python scalars` (pykalman, quantecon, commpy, tmm) or `float() argument must be … not 'tuple'` (pymap3d). `--probe` fixes all of them. Without `--probe`, `init` only warns `type not shown by the code, assumed Real`, not that it may be an array.
9. **Methods that need simulation time aren't bound to it.** simpy `Environment.run(until)`: `until` becomes a fixed input, so the second step fails with `until (1.0) must be greater than the current simulation time`. Without `--probe`, `run` returns `None` and the step fails with `y is None`.
10. **Factories: `init` without `--probe` can't see the call method's arguments** (tellurium `loada(...).oneStep`: `--start names that are not arguments of the model: ['currentTime', 'stepSize']`). It also writes no outputs for mendeleev's `element()` (returns an ORM object). Both work with `--probe`.
11. **Classes: outputs are 0 at t = 0 in the runner.** blackscholes (`BlackScholesCall(...).price()`) shows `y = 0.0` in the first row of the Liqo CSV and the right value from t = 1. Functions (quantlib) have the value at t = 0.
12. **Libraries that need numpy arrays** (thermofeel `calculate_heat_index_simplified` calls `np.nonzero` on its input) fail with scalar inputs in the probe and in the FMU. `init` doesn't retry the probe with 0-d / 1-element arrays.
13. **A deploy hangs with no timeout.** antropy's run on `fmu-remote` stopped after `Connection established!` and didn't finish within 5 minutes (it takes under a second on Windows). Cause not investigated; numba compiling on first use in the container is a guess. Separately, a `docker build` hung in "exporting layers" (statsmodels) and had to be killed. That's Docker Desktop, not fmugen; the retry passed.

Problem 1 of round 2 (orphaned backends) wasn't checked this time.

---

## Results

Columns:
- **init / probe**: whether `init` and `init --probe` wrote a config. ✓ = written; ✗ = `init` stopped with an error.
- **Windows**: build + simulate with the best config ("p" = the `--probe` config, "c" = the code-only config; ✓/✗ for each).
- **Liqo**: the run Job on `fmu-remote`.

| # | Model (domain) | `init` options | init | probe | Windows c / p | Liqo | Notes |
|---|---|---|---|---|---|---|---|
| 1 | `numpy_financial:pmt` (finance) | rate, nper, pv | ✓ | ✓ | ✓ / ✓ | ✓ | −1199.10 = direct. Warning: `fv` typed Integer (default 0). |
| 2 | `QuantLib:blackFormula` (finance, SWIG C++) | optionType, strike, forward, stdDev | ✓ | ✓ | ✓ / ✓ | ✓ | 10.9056 = direct |
| 3 | `blackscholes:BlackScholesCall` `--call price` (finance) | S, K, T, r, sigma | ✓ | ✓ | ✓ / ✓ | ✓ | 10.4506 = direct; 0 at t = 0 (problem 11) |
| 4 | `pyxirr:npv` (finance, Rust) | rate, `amounts=call:builtins:list([...])` | ✓ | ✓ | no outputs / ✓ | ✓ | 8.0445 = direct. Without the probe: no source (Rust), so no outputs. |
| 5 | `quantecon:LinearStateSpace` `--call stationary_distributions` (economics) | A, C, G as `call:numpy:array` | ✓ | ✓ | ✗ / ✓ | ✓ | Problem 8 without the probe. With it, 15 outputs (Σx = 5.263 = 1/(1−0.9²)). |
| 6 | `nashpy:Game` (game theory) | `M_r=call:numpy:array(...)` | ✗ | ✗ | — | — | Problem 1 (`Game(*A)`) |
| 7 | `simpy:Environment` `--call run` (discrete events) | until=1.0 | ✓ | ✓ | ✗ / ✗ | ✗ | Problem 9 |
| 8 | `transforms3d.euler:euler2quat` (rotations) | ai, aj, ak | ✓ | ✓ | no outputs / ✓ | ✓ | Quaternion = direct. Without the probe the array result is commented out, so no outputs. |
| 9 | `pyquaternion:Quaternion` `--call rotate` (rotations) | axis, angle, vector | ✗ | ✗ | — | — | Problem 1 |
| 10 | `pymap3d:geodetic2enu` (geodesy) | 6 coordinates | ✓ | ✓ | ✗ / ✓ | ✓ | (8539.5, −11098.9, 84.6) = direct; problem 8 without the probe |
| 11 | `obspy.geodetics:gps2dist_azimuth` (seismology) | 4 coordinates | ✓ | ✓ | no outputs / ✓ | ✓ | (438072.49 m, 73.70°, 256.95°) = direct. Without the probe: "return statements return different shapes", no outputs. |
| 12 | `haversine:haversine` (navigation) | `point1/2=call:builtins:tuple([...])` | ✓ | ✓ | ✓ / ✓ | ✓ | 505.62 km = direct |
| 13 | `openap:Thrust` `--call climb` (aviation) | ac=A320, tas, alt, roc | ✓ | ✓ | ✓ / ✓ | ✓ | 90577.45 N = direct |
| 14 | `pyorbital.astronomy:sun_zenith_angle` (satellites) | lon, lat | ✓ | ✓ | ✓ / ✓ | ✓ | `utc_time` bound to `[time]` from its name (warning shown); 145.02° at 00:00:03 |
| 15 | `timezonefinder:TimezoneFinder` `--call timezone_at` (geo lookup) | lng, lat | ✓ | ✓ | ✓ / ✓ | ✓ | String output `Europe/Madrid` = direct (seen in the Liqo CSV; FMPy's result array has no strings). The object can't be pickled (warning). |
| 16 | `shapely:Point` (geometry) | x, y | ✓ | ✓ | no outputs / ✓ | ✓ | Without the probe: 26 properties commented out, no outputs. With it: `area`, `bounds`, `is_valid`, … |
| 17 | `meteocalc:heat_index` (weather) | temperature, humidity | ✓ | ✓ | ✓ / ✓ | ✓ | 25.52 = direct (the library works in °F by default; no unit in the config) |
| 18 | `thermofeel:calculate_heat_index_simplified` (weather, ECMWF) | t2_k, rh | ✓ | ✓ | ✗ / ✗ | ✗ | Problem 12 |
| 19 | `pythermalcomfort.models:pmv_ppd_iso` (building comfort) | tdb, tr, vr, rh, met, clo | ✓ | ✓ | ✓ / ✓ | ✓ | PMV 0.08, PPD 5.1, `tsv = "Neutral"` (String) = direct. A dataclass result was split into fields correctly. |
| 20 | `PyCO2SYS:sys` (ocean chemistry) | par1, par2, par1_type, par2_type | ✓ | ✓ | build ✗ | — | Problem 5 |
| 21 | `pedon:Genuchten` `--call theta` (soil physics) | k_s, theta_r, theta_s, alpha, n, h | ✓ | ✓ | ✓ / ✓ | ✓ | 0.27373 = direct |
| 22 | `pygfunction.heat_transfer:finite_line_source` (geothermal) | time, alpha, 2 boreholes as `call:` | ✓ | ✓ | build ✗ | — | Problem 4 (`time`). A first try with `Borehole` alone stopped at "cannot tell which method runs a step" (correct; my choice). |
| 23 | `tmm:coh_tmm` (thin-film optics) | pol, n_list, d_list, th_0, lam_vac | ✓ | ✓ | ✗ / ✓ | ✓ | First try with `float("inf")`: problems 2 and 3. Retried with the `1e400` literal: R = 0.13572, T = 0.86428. Complex `r`, `t` commented out as real/imag pairs (round 2 behaviour). |
| 24 | `scipy.signal:lfilter` (DSP) | b, a, x as arrays | ✓ | ✓ | no outputs / ✓ | ✓ | [0.5, 1.5, 2.5, 3.5] = direct |
| 25 | `pywt:dwt` (wavelets) | data, wavelet=db2 | ✓ | ✓ | ✓ / ✓ | ✓ | Tuple of arrays (cA, cD) → `y0`, `y1` |
| 26 | `librosa:hz_to_mel` (audio) | frequencies=440 | ✓ | ✓ | ✓ / ✓ | ✓ | 6.6 = direct |
| 27 | `pyloudnorm:Meter` `--call integrated_loudness` (audio) | rate, data | ✓ | ✓ | ✗ / ✗ | ✗ | Problems 2 and 3 (nested `numpy.linspace` in `call:`) |
| 28 | `commpy.modulation:QAMModem` `--call modulate` (telecom) | m=4, input_bits | ✓ | ✓ | ✗ / no outputs | ✓ (no outputs) | Without the probe: problem 8. With it, the complex symbols are commented out, so the FMU has no outputs. |
| 29 | `skimage.color:rgb2hsv` (imaging) | rgb array | ✓ | ✓ | no outputs / ✓ | ✓ | [0.5833, 0.6667, 0.6] = direct |
| 30 | `cv2:KalmanFilter` `--call predict` (computer vision, C++) | dynamParams, measureParams | ✓ | ✓ | no outputs / ✓ | ✓ | `predict`'s signature can't be read (warning, correct). Can't be pickled. Output [[0],[0]]. |
| 31 | `heartpy:process` (cardiology) | hrdata, sample_rate | ✗ / ✓* | ✓* | ✗ / ✗ | ✗ | First try: heartpy needs `pkg_resources` (setuptools < 81 added). Then `call:heartpy:get_data("data.csv")` fails at run time, since the file isn't in the working folder (my input) → problem 3. |
| 32 | `antropy:perm_entropy` (signal complexity) | x, normalize | ✓ | ✓ | ✓ / ✓ | **hung** | First try with nested `numpy.linspace`: problems 2 and 3. Retried with a literal list: 0.86051 on Windows. On `fmu-remote`, problem 13. |
| 33 | `rainflow:count_cycles` (fatigue) | series | ✓ | ✓ | ✓ / ✓ | ✓ | List of (range, count) pairs → 4×2 array = direct |
| 34 | `skfuzzy:interp_membership` (fuzzy logic) | x, xmf, xx | ✗ / ✓* | ✓* | ✓ / ✓ | ✓ | scikit-fuzzy doesn't declare scipy, packaging or networkx (installed by hand). 0.7 = direct. |
| 35 | `statsmodels.stats.proportion:proportion_confint` (statistics) | count, nobs | ✓ | ✓ | ✓ / ✓ | ✓ | (0.30398, 0.49602) = direct. Without the probe: `y0`, `y1`; with it: `y[2]`. |
| 36 | `chaospy:Normal` `--call pdf` (uncertainty quantification) | mu, sigma, x | — | — | — | — | **Install failed** on Windows/Python 3.13 (its dependency `numpoly` has no wheel and needs MSVC). Not an fmugen issue. |
| 37 | `openturns:Normal` `--call computePDF` (UQ, replaces chaospy) | mu, sigma, x | ✓ | ✓ | ✗ / ✗ | ✗ | Problem 6 |
| 38 | `uncertainties:ufloat` (error propagation) | nominal_value, std_dev | ✓ | ✓ | ✗ / ✗ | ✗ | Problem 7 |
| 39 | `pykalman:KalmanFilter` `--call filter_update` (estimation) | mean, covariance, observation | ✓ | ✓ | ✗ / ✓ | ✓ | Problem 8 without the probe; with it, mean 0.6667 = direct |
| 40 | `numdifftools:Derivative` (numerics) | `fun=call:numpy:sin`, x | ✓ | ✓ | ✗ / ✗ | ✗ | Problem 2 (no way to pass a function) → problem 3 |
| 41 | `pymunk:Space` `--call step` (2D physics) | dt | ✓ | ✓ | ✓ / ✓ | ✓ | Runs, but only constant settings are outputs. `gravity` (a `Vec2d`), `bodies` and `shapes` are commented out as properties of unknown type, even with `--probe`. |
| 42 | `anastruct:SystemElements` `--call solve` (structural FEM) | 4 `--setup` calls (element, supports, load) | ✓ | ✓ | ✗ / ✓ | ✓ | Displacements = direct. Without the probe: `buckling_factor is None` fails the step (round 2's problem 4). `--setup` with lists worked. |
| 43 | `electricpy:powerset` (power engineering) | P, PF | ✓ | ✓ | no outputs / ✓ | ✓ | (100, 48.43, 111.11, 0.9) = direct |
| 44 | `pyfluids:Fluid` `--call with_state` (thermophysical properties) | name, two `Input`s | ✓ | ✓ | ✗ / ✗ | ✗ | Problem 2 (`FluidsList.Water` gets called) → 3 |
| 45 | `mendeleev:element` (chemistry, SQLAlchemy) | ids=Fe | ✓ | ✓ | no outputs / ✓ | ✓ | Problem 10 without the probe. With it, ~80 outputs (strings and numbers). `ec` skipped; ints typed Real, with a warning. |
| 46 | `radioactivedecay:Inventory` `--call decay` (nuclear) | contents, decay_time | ✓ | ✓ | build ✗ | — | Problem 4 (`units`). With the probe, the dict result `contents.N-14` was skipped as an invalid name, so there were no outputs. The first try used a wrong argument name (mine). |
| 47 | `Bio.SeqUtils:gc_fraction` (bioinformatics) | seq (String) | ✓ | ✓ | ✓ / ✓ | ✓ | 0.5 = direct |
| 48 | `pyteomics.mass:calculate_mass` (proteomics) | sequence | ✓ | ✓ | ✓ / ✓ | ✓ | 799.35996 = direct, passed through `**kwargs` (warning) |
| 49 | `rdkit.Chem.Descriptors:MolWt` (cheminformatics) | `mol=call:rdkit.Chem:MolFromSmiles("CCO")` | ✗ | ✗ | — | — | Problem 1 |
| 50 | `tellurium:loada` `--call oneStep` (systems biology, SBML) | Antimony model, currentTime, stepSize | ✗ | ✓ | — / ✓ | **image ✗** | Problem 10 without the probe. With it, it runs, but the only output is `oneStep`'s return (always 0.1, since `currentTime` is a fixed input), not the species. The Linux image failed: `No module named 'tesbml'` (a tellurium dependency missing on Linux). |
| — | `astropy.cosmology:FlatLambdaCDM` `--call age` (cosmology) | H0, Om0, z | ✓ | ✓ | build ✗ | — | Problem 4. Counted as an extra model (51 tried, 50 counted, excluding chaospy, which couldn't be installed). |

\* after adding the missing dependency of the library.

---

## Deployment with Liqo: details

- `bash docker/liqo/up.sh` worked unchanged: two kind clusters, `fmu-remote` Ready as a virtual node about 5 minutes after start.
- Per model: `docker build` (only the layer that runs `build_fmu.py` reran), `kind load` into both clusters, `kubectl set image` on `opcua-server` and `streamlit-ui`, then the Job. The Job used the same spec as `KubernetesRuns.start` in [streamlit_app.py](../docker/app/streamlit_app.py), with `STEP_DELAY=0` and 0–3 s.
- All 42 Jobs that started were scheduled on `fmu-remote`. Runs succeeded on `fmu-remote` exactly where they succeeded on Windows. Failed runs showed the FMI error in the pod log (`fmi3ExitInitializationMode failed …`, `Failed to instantiate FMU`), with no more reason than on Windows (round 2's problem 7 applies in the cluster too).
- The OPC UA server came up for every FMU, including ones with String, Boolean, 2-D array and many-output variables (mendeleev, anastruct `system_matrix`, quantecon).
- The image builds don't need `--vendor`: `[model] requirements` are installed into the image. **`init` doesn't write `requirements`**, so for every model they had to be added by hand to deploy. Without them, `build_fmu.py` fails at import.
- Docker Desktop: one `docker build` hung in "exporting layers" (statsmodels) with 24 GB of build cache. The retry passed.

## Versions

Latest on PyPI on 2026-10-07 for Python 3.13: numpy-financial, QuantLib, blackscholes, pyxirr, quantecon, nashpy, simpy, transforms3d, pyquaternion, pymap3d, obspy, haversine, openap, pyorbital, timezonefinder, shapely, meteocalc, thermofeel, pythermalcomfort, PyCO2SYS, pedon, pygfunction, tmm, scipy, PyWavelets, librosa, pyloudnorm, scikit-commpy, scikit-image, opencv-python-headless, heartpy, antropy, rainflow, scikit-fuzzy, statsmodels, chaospy, openturns, uncertainties, pykalman, numdifftools, pymunk, anastruct, electricpy, pyfluids, mendeleev, radioactivedecay, biopython, pyteomics, rdkit, tellurium, astropy.
