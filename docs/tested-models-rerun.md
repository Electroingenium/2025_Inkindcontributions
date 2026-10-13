# Tested models, rerun (2026-10-09)

All models from [tested-models.md](tested-models.md), [round 2](tested-models-round2.md) and [round 3](tested-models-round3.md), rerun with fmugen at `0e0b670` (branch `bugfixing`). Each model went through:

1. `fmugen init` (code only)
2. `fmugen init --probe`
3. `fmugen build --capture-output` on each config `init` wrote (and on the committed `fmugen.toml` for the repository examples), then `fmpy.simulate_fmu` for 3 s with 1 s outputs
4. `fmugen build --capture-output --compile pyinstaller` on the best config (the `--probe` one when it simulated), then the same simulation

**FMI 2 by default.** A model was rerun with FMI 3 only when no FMI 2 config simulated. The same `init` options as the original runs were used (round 2's were rebuilt from the configs it wrote; the `…` placeholders of round 1, e.g. audio samples and time series, were filled with generated values). Models that had hand-written configs in earlier rounds (`PropsSI`, `fluids.units`, `JOS3`, PyTCI, cantera, metpy) only got `init` here. The pvlib composite FMU was not rerun (it isn't one model).

Setup: Windows 11, Python 3.13, uv venvs (round 1: two new ones; round 2: the shared `ctv` venv; round 3: its per-model venvs), fmugen editable from this checkout, FMPy 0.3.32, PyInstaller 6.22.3, UniFMU 0.14. Six models ran in parallel.

## Fixes after the rerun (2026-10-09)

Four findings of this rerun were fixed or corrected the same day, two more on 2026-10-13. The per-model table below still shows the first run.

| Finding | What it was | Result |
|---|---|---|
| python-control `StateSpace` "regression" | **Not a regression: my test setup.** Round 2's options were rebuilt from the configs that run wrote, keeping only the starts marked `# start from --start`. With `--probe`, `init` writes array starts without that marker, so `--start x=[1.0, 0.0]` and `u=[0.0]` were dropped. No other model lost a start. | With the original starts, `init --probe` writes the 2026-10-07 config again. FMI 2: y = (0.0, −2.0) = A·x. The code-only config still fails, as before (array result assumed a single Real). |
| `--compile` leaves out package data, modules and extensions | `compile_fmu` gave the freezer only the modules the runtime imports by name. Constants written `{ call = "module:fn(...)" }` were also missed. | fmugen now also collects the model's packages with all their submodules, the data files, binaries and metadata of their whole dependency tree, and more ([packaging.md](packaging.md#what-the-compiler-is-told)). **All 22 compiled FMUs that failed now simulate**, among them the 3 PyTorch ones. The cause of each was found by running the frozen backend directly: [unifmu-limitations.md §13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer). skops also needs `scikit-learn` in `[model] requirements`, since its model is unpickled (added by hand). |
| `stamp_guid` reads every file whole | `MemoryError` on surfaces's large frozen file. `_write_zip` read each file whole too. | Both now stream the files (`hashlib.file_digest`, `shutil.copyfileobj`). GUIDs and zips are unchanged (the reproducible-build test passes). surfaces compiles (294 MB) and simulates. |
| mendeleev `init --probe` crash (2026-10-13) | **A regression** since round 3: listing the result's properties with `inspect.getmembers` reads each attribute on the class, which runs SQLAlchemy's hybrid properties; mendeleev's `ionenergies` raises `NotImplementedError` there, and `init` stopped with a raw traceback. | Properties are now looked up with `inspect.getattr_static`, which runs nothing. `--probe` writes 79 variables; FMI 2: Fe gives atomic_number 26, atomic_weight 55.845. |
| sgp4: misleading `--start names that are not arguments of the model` (2026-10-13) | `Satrec.twoline2rv` and `Satrec.sgp4` are C built-ins with no signature, so no `--start` name can be placed. A C built-in factory given with `--call` also crashed with a raw `ValueError`. | `fmugen: error: --start fr, jd, line1, line2: cannot tell which arguments these are, since Satrec.twoline2rv and Satrec.sgp4 have no signature (e.g. a C built-in); write the config by hand, with to = "pos:N" …`. sgp4 still needs a hand config. |
| `init -o` outside a script model's folder | a raw `ValueError … is not in the subpath of …` traceback | `fmugen: error: the config must be in the folder of psychrometry.py or a folder above it, …`, naming where to write it. |

**After the fixes:**

| | Before | After |
|---|---|---|
| `init` writes a config (of 116; the 2 FMI 3 examples have no `init` run) | 110 | **111** (nashpy, with a real method) |
| `init --probe` writes a config | 112 | **115** (mendeleev; heartpy and nashpy, with corrected inputs) |
| Simulate correctly with FMI 2 | 106 | **108** (StateSpace, heartpy) |
| Fail with FMI 2 and FMI 3 | 12 | **10** |
| Compiled FMU simulates | 83 | **106**: the 22, plus surfaces |

Compiled with the final code: the 23 fixed models, plus 10 that already compiled (gsw, pvwatts_dc, Chronos, haversine, QuantLib, simple_pid, timezonefinder, pythermalcomfort, mesa, GHFilter), which still simulate. The FMUs grew by 0 to 25 MB (pvwatts_dc 133 → 157 MB, mesa 111 → 137 MB, gsw 103 → 104 MB, haversine unchanged at 24 MB). Granite TTM (3,170 outputs) and Chronos also ship their `.py` sources, see [packaging.md](packaging.md#what-the-compiler-is-told).

**The models `init` wrote no config for.** Of the 8 without a code-only config and the 6 without a `--probe` one, 2 are the FMI 3 examples (`examples/kalman`, `examples/sampled_pid`), where `init` wasn't run. The 4 that only `--probe` handles (silero_vad, Granite `get_model`, pyromat, `joblib:load`) are problem 7. Of the 4 that failed both ways: mendeleev and sgp4 are the fixes above; heartpy and nashpy were my inputs. heartpy with its own `data/data.csv` given by full path gets a `--probe` config (20 variables). heartpy then builds and simulates with FMI 2 (e.g. bpm 58.9). nashpy 0.0.43 has no `is_zero_sum` method. With a real one (`support_enumeration`) both modes write a config, but the method returns a generator: `--probe` finds no outputs, and the code-only config fails the step (`float() argument must be … not 'generator'`). nashpy and sgp4 stay among the 10 failures.

Not checked: Nuitka (not installed here), and the 33 models' compiled values against their uncompiled runs (only that they simulate).

## Summary (first run)

| | Count |
|---|---|
| Models | 118 (38 round 1 incl. 5 examples, 30 round 2, 50 round 3) |
| `init` writes a config | 110 |
| `init --probe` writes a config | 112 |
| **Simulate correctly with FMI 2** (at least one config) | **106** |
| …of which the code-only config already simulates | 65 |
| Pass only with FMI 3 | 0 |
| Fail with FMI 2 and FMI 3 | 12 |
| `--compile pyinstaller` builds | 114 of 116 tried |
| **Compiled FMU simulates** | **83** |
| Compiled FMU fails where the non-compiled one passes | 22 |

The FMI 3 retry never rescued a model: each of the 12 fails the same way in both versions.

### Problems found

**`--compile pyinstaller`** (new, not tested before):

1. **Package data files, modules and extensions left out of the frozen FMU: 22 compiled FMUs fail** whose uncompiled FMU passes. The frozen backend dies at instantiation or initialization:
   - Data files: iapws (`VERSION`; `_TSat_P`, `IAPWS97`), ahrs (`WMM2025/WMM.COF`; Madgwick, Mahony), openap (`data/aircraft/_synonym.csv`), radioactivedecay (`decay_data.npz`), pyromat (`registry`), tellurium (`antimony`), mendeleev (`elements.db`), pymsis (`msis21.parm`), simglucose (`params/vpatient_params.csv`), thermo/chemicals (`Identifiers/…pubchem…`), hplib (its CSV database), pybamm (parameter sets: `'Marquis2019' is not a valid parameter set`), roboticstoolbox (`meshes/FRANKA-EMIKA/Panda`), silero-vad (`No module named 'silero_vad.data'`, the ONNX file).
   - Modules: py_vollib (`No module named 'py_vollib'`); skops (`No module named 'huggingface_hub'`, imported only by the `hf_hub_download` constant).
   - Extensions: cantera (`ImportError: dynamic module does not define module export function (PyInit_drawnetwork)`).
   - PyTorch: Granite TTM, SB3 PPO and TorchANI build (290–300 MB), but the backend exits with status 1 at instantiation. Their backend error wasn't looked at. Chronos (also PyTorch) works (323 MB).

   fmugen would need to pass `--collect-data` / `--collect-submodules` (or hooks) for the model's packages.

   For 12 of these (`_TSat_P`, `IAPWS97`, Madgwick, Mahony, openap, radioactivedecay, pyromat, tellurium, mendeleev, pymsis, py_vollib, cantera), the importer saw no error status: UniFMU panicked (`zeromq-0.4.1/src/rep.rs:168: not yet implemented`) and **aborted the importer's process**, hiding the backend's traceback. The errors above were found by running each frozen backend directly against a ZeroMQ socket. The panic is UniFMU's handling of a backend that exits mid-call, not the cause: see [unifmu-limitations.md §13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer).
2. **`MemoryError` in `stamp_guid`** for surfaces: [description.py:338](../src/fmugen/description.py#L338) reads each FMU file whole (`file.read_bytes()`) to hash it, which runs out of memory on a large frozen file. Hashing in chunks would fix it.
3. Compiled FMUs are large: 25 MB (pure-Python libraries) to 135 MB (pvlib, gymnasium), 300+ MB with PyTorch. A compile took 3–15 minutes.

**`init` (code only)** — known limits, mostly fixed by `--probe` (102 of 112 probe configs simulate, vs 65 code-only):

4. **Results that are arrays, tuples, dicts or objects are typed as a single Real**, and the run fails: `y is an array of shape [4], not a single value: … fmugen init --probe finds them` (aoi, Q_discrete_white_noise, colour, neurokit2, pymap3d, pywt, rainflow, tmm, commpy, torchani, …), `float() argument must be … not 'dict'/'DataFrame'/'SE3'/'Inventory'/'Solution'`. The error message points to `--probe`, which fixes each of them.
5. **String results typed Real** (thermo `CAS`, pythermalcomfort `tsv`, `sports_heat_stress_risk` advice text): `set type = "String"`; fixed by `--probe`.
6. **Integer outputs that overflow**: CartPole and Pendulum's `np_random_seed` (a 128-bit seed) is typed Integer: `… is out of range for Integer`. `--probe` leaves it out.
7. `init` without `--probe` refuses `--start` names it can't see in a factory or `**kwargs` (silero_vad `x`/`sr`, Granite `past_values`, pyromat `T`, skops `X`): `--start names that are not arguments of the model`. With `--probe` they work.
8. **Example scripts: `init -o` outside the model's folder fails** with `ValueError: '…\psychrometry.py' is not in the subpath of '…'` (a raw traceback, not a `fmugen: error`). With the config next to the model, both examples work.

**Still failing (both FMI versions), as in earlier rounds:** `PropsSI` (C extension, no signature: hand config needed), `fluids.units` ×2 (pint: `1.0 has no quantity`; hand config needed), metpy (pint), pyet (`'float' object has no attribute 'time'`: needs pandas Series), psychrolib (`GetHumRatioFromRelHum` is a numba ufunc, which takes no keyword arguments: `unexpected keyword arguments to ufunc`. In FMI 2 with logging on, FMPy then crashes with an access violation, because the traceback contains `%s`: UniFMU bug [§12](unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings)), python-control `StateSpace` (`len(x) must be equal to number of states`: a start value my rebuilt options dropped, not a regression, see [above](#fixes-after-the-rerun-2026-10-09)), simpy (`until` not bound to time), pyquaternion (`*args` constructor gets the step's arguments), heartpy (`data.csv` not in the working folder: my input), nashpy (`Game has no method 'is_zero_sum'`: my input), sgp4 (C built-in factory: `--start names that are not arguments`).

**Fixed since the earlier rounds (now pass):** openturns `Normal`, uncertainties `ufloat`, thermofeel (0-d array retry), PyCO2SYS `sys`, pygfunction (`time` argument), radioactivedecay (`units`), astropy, rdkit `MolWt`, mesa, river, pyloudnorm, numdifftools, pyfluids, Madgwick/Mahony with FMI 2, all 6 neural networks with FMI 2 (arrays as one scalar per element).

## Results

Columns: **init / init --probe**: config written. **build + simulate**: per config (`plain` = code-only, `probe`, `repo` = the committed config). **compile**: the config compiled, the result and the FMU size. **First error**: the first failing step's error (from `init`, the build, or the simulation log).

## Round 1 (tested-models.md)

| Model | FMI | init | init --probe | build + simulate (per config) | compile (pyinstaller) + simulate | First error |
|---|---|---|---|---|---|---|
| `psychrometry.py:compute_balances_simplified` (example) | 2 | ✓* | ✓* | plain ✓ / probe ✓ / repo ✓ | repo: ✓, 128.7 MB | *`init` only works with `-o` inside the model's folder: with `-o` elsewhere it stops with `ValueError: … is not in the subpath of …`. Rerun in the folder: 6 outputs. |
| `simple_pid:PID` | 2 | ✓ | ✓ | plain ✓ / probe ✓ / repo ✓ | probe: ✓, 128.7 MB |  |
| `building_physics.py:Zone` (example) | 2 | ✓* | ✓* | plain ✓ / probe ✓ / repo ✓† | repo: ✓†, 128.7 MB | *as psychrometry. †The repo config fixes `step_size = 3600`, so the generic 1 s run is refused (correct); simulated at 3600 s steps, plain and compiled give the same values. |
| `filterpy.kalman:KalmanFilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.8 MB | The repo config needs FMI 3: see its own row. |
| `simple_pid:PID` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.7 MB | The repo config needs FMI 3: see its own row. |
| `pvlib.pvsystem:pvwatts_dc` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.0 MB |  |
| `pvlib.temperature:sapm_cell` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.0 MB |  |
| `pvlib.atmosphere:alt2pres` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.0 MB |  |
| `pvlib.irradiance:aoi` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 133.0 MB | Exception('Failed to instantiate model') |
| `ht.hx:effectiveness_from_NTU` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 134.1 MB |  |
| `chemicals.vapor_pressure:Antoine` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 134.6 MB |  |
| `fluids.friction:friction_factor` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.8 MB |  |
| `fluids.core:Reynolds` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 133.8 MB |  |
| `ht.conv_internal:Nu_conv_internal` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 134.1 MB |  |
| `iapws.iapws97:_TSat_P` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 128.8 MB | compiled: the frozen backend exits (iapws/VERSION missing); UniFMU then aborts the importer (rep.rs:168 panic, [§13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)) |
| `filterpy.common:Q_discrete_white_noise` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 128.8 MB | TypeError: y is an array of shape [2, 2], not a single value: give it dimensions = [2, 2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `psychrolib:GetHumRatioFromRelHum` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 128.7 MB | FMI 2: OSError('exception: access violation reading 0x00000000000009AA') — FMI 3: TypeError: unexpected keyword arguments to ufunc: 'Pressure', 'RelHum', 'TDryBulb' |
| `CoolProp.CoolProp:PropsSI` | 2 → 3 | ✓ | ✓ | plain ✗ / probe ✗ | probe: ✗ | FMI 2: fmugen: error: the config defines no FMU variables: add [inputs]/[parameters] and [outputs] (the model's arguments and results could not be inferred) — FMI 3: fmugen: error: the config defines no FMU variables: add [inputs]/[parameters] and [outputs] (the model's arguments and results could not be inferred) |
| `iapws:IAPWS97` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: build ✓, sim ✗, 128.8 MB | TypeError: float() argument must be a string or a real number, not 'dict' |
| `filterpy.gh:GHFilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.8 MB |  |
| `tclab:TCLabModel` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.8 MB |  |
| `gymnasium.envs.classic_control.cartpole:CartPoleEnv` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 135.6 MB | ValueError: 147626572821865577400907706530850663577 is out of range for Integer |
| `gymnasium.envs.classic_control.pendulum:PendulumEnv` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 135.6 MB | ValueError: 172939238529957257140098871392319507192 is out of range for Integer |
| `ahrs.filters:Madgwick` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 129.0 MB | compiled: the frozen backend exits (ahrs/utils/WMM2025/WMM.COF missing); UniFMU then aborts the importer (rep.rs:168 panic, [§13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)) |
| `ahrs.filters:Mahony` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: build ✓, sim ✗, 129.0 MB | TypeError: b is an array of shape [3], not a single value: give it dimensions = [3] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `fluids.units:Reynolds` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 133.8 MB | FMI 2: TypeError: 1.0 has no quantity — FMI 3: TypeError: 1.0 has no quantity |
| `fluids.units:head_from_P` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 133.8 MB | FMI 2: TypeError: 100000.0 has no quantity — FMI 3: TypeError: 100000.0 has no quantity |
| `highway_env.envs.highway_env:HighwayEnv` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 135.8 MB | TypeError: y0 is an array of shape [5, 5], not a single value: give it dimensions = [5, 5] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pvlib.solarposition:get_solarposition` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 133.0 MB | TypeError: float() argument must be a string or a real number, not 'DataFrame' |
| `pythermalcomfort.models:sports_heat_stress_risk` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 128.9 MB | ValueError: could not convert string to float: 'Increase frequency and/or duration of rest breaks' |
| `pvlib.iotools:read_tmy3` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 133.0 MB | TypeError: float() argument must be a string or a real number, not 'DataFrame' |
| `pythermalcomfort.models.jos3:JOS3` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 128.9 MB |  |
| `chronos:ChronosBoltPipeline` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 322.8 MB |  |
| `silero_vad:load_silero_vad` | 2 | ✗ | ✓ | probe ✓ | probe: build ✓, sim ✗, 291.7 MB | fmugen: error: --start names that are not arguments of the model: ['sr', 'x'] |
| `tsfm_public.toolkit.get_model:get_model` | 2 | ✗ | ✓ | probe ✓ | probe: build ✓, sim ✗, 295.5 MB | fmugen: error: --start names that are not arguments of the model: ['past_values'] |
| `stable_baselines3:PPO` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 292.4 MB | Exception('Failed to instantiate model') |
| `surfaces.test_functions.machine_learning.hyperparameter_optimization.tabular.regression.test_functions.gradient_boosting_regressor:GradientBoostingRegressorFunction` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✗ | MemoryError |
| `torchani.models:ANI2x` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: build ✓, sim ✗, 296.0 MB | TypeError: species is an array of shape [1, 5], not a single value: give it dimensions = [1, 5] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `examples/kalman` repo config (FMI 3 only: structural parameters, clock) | 3 | — | — | repo ✓‡ | ✗ (see notes) | ‡Fails the generic run (the clock is never ticked); `examples/kalman/run.py` runs it correctly. Compiled: built in the batch run; a separate rebuild failed in PyInstaller (log truncated). |
| `examples/sampled_pid` repo config (FMI 3 only: clocks) | 3 | — | — | repo ✓ | repo: ✓, 128.7 MB | |

## Round 2 (tested-models-round2.md)

| Model | FMI | init | init --probe | build + simulate (per config) | compile (pyinstaller) + simulate | First error |
|---|---|---|---|---|---|---|
| `ambiance:Atmosphere` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |
| `astral.sun:elevation` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.9 MB |  |
| `cantera:Solution` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 105.9 MB | compiled: the frozen backend exits (ImportError: PyInit_drawnetwork); UniFMU then aborts the importer (rep.rs:168 panic, [§13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)) |
| `colour.temperature:CCT_to_xy_CIE_D` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 113.1 MB | TypeError: y is an array of shape [2], not a single value: give it dimensions = [2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `control:StateSpace` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 103.0 MB | FMI 2: ValueError: len(x) must be equal to number of states — FMI 3: ValueError: len(x) must be equal to number of states |
| `erfa:gmst06` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.8 MB |  |
| `gsw:rho` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 103.3 MB |  |
| `hplib.hplib:HeatPump` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 101.5 MB | RuntimeError: [model] constants.parameters = "hplib.hplib:get_parameters(model='Generic', group_id=1, t_in=-7, t_out=52, p_th=10000)" failed: FileNotFoundError(2, 'No such file or directory') |
| `impedance.models.circuits:Randles` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 103.7 MB | TypeError: y is an array of shape [4], not a single value: give it dimensions = [4] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `mesa.examples:BoltzmannWealth` | 2 | ✓ | ✓ | plain ✗ / probe ✓ | probe: ✓, 111.4 MB | fmugen: error: the config defines no FMU variables: add [inputs]/[parameters] and [outputs] (the model's arguments and results could not be inferred) |
| `metpy.calc:dewpoint_from_relative_humidity` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 111.0 MB | FMI 2: ValueError: This function changed in version(s) ['1.0']--double check that the function is being called properly. — FMI 3: ValueError: This function changed in version(s) ['1.0']--double check that the function is being called properly. |
| `neurokit2:ecg_simulate` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 114.1 MB | TypeError: y is an array of shape [100], not a single value: give it dimensions = [100] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pandapower:runpp` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 127.9 MB |  |
| `ppigrf:igrf` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |
| `pybamm:Simulation` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: build ✓, sim ✗, 130.2 MB | TypeError: float() argument must be a string or a real number, not 'Solution' |
| `pyet:pm_fao56` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 111.1 MB | FMI 2: AttributeError: 'float' object has no attribute 'time' — FMI 3: AttributeError: 'float' object has no attribute 'time' |
| `pymsis:calculate` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 102.5 MB | compiled: the frozen backend exits (msis21.parm missing); UniFMU then aborts the importer (rep.rs:168 panic, [§13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)) |
| `pyproj:Transformer` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 107.9 MB | TypeError: y is a tuple of shape [2], not a single value: give it dimensions = [2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pyromat:get` | 2 | ✗ | ✓ | probe ✓ | probe: build ✓, sim ✗, 101.5 MB | fmugen: error: --start names that are not arguments of the model: ['T'] |
| `pysolar.solar:get_altitude` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 101.5 MB | pysolar.tzinfo_check.NoTimeZoneInfoError: datetime value '2026-10-09 00:00:00' given for arg 'when' should be made timezone-aware. |
| `PyTCI.models.propofol:Marsh` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |
| `river.linear_model:LinearRegression` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 102.9 MB | LookupError: max_cum_l1: cannot read attribute 'max_cum_l1' (AttributeError("'LinearRegression' object has no attribute 'max_cum_l1'")) |
| `roboticstoolbox.models.DH:Panda` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: build ✓, sim ✗, 112.5 MB | TypeError: float() argument must be a string or a real number, not 'SE3' |
| `seirsplus.models:SEIRSModel` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 111.2 MB |  |
| `sgp4.api:Satrec` | 2 → 3 | ✗ | ✗ |  | — | FMI 2: fmugen: error: --start names that are not arguments of the model: ['fr', 'jd', 'line1', 'line2'] — FMI 3: fmugen: error: --start names that are not arguments of the model: ['fr', 'jd', 'line1', 'line2'] |
| `simglucose.patient.t1dpatient:T1DPatient` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 101.7 MB | FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Users\\TomasRobino\\AppData\\Local\\Temp\\tmpbukrcnai\\resources\\dist\\main\\_internal\\simglucose\\params\\vpatient_params.csv' |
| `joblib:load` | 2 | ✗ | ✓ | probe ✓ | probe: build ✓, sim ✗, 101.9 MB | fmugen: error: --start names that are not arguments of the model: ['X'] |
| `thermo:Chemical` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: build ✓, sim ✗, 112.8 MB | TypeError: CAS is a string ('7732-18-5'), not a Real: set type = "String" for it in the config |
| `py_vollib.black_scholes:black_scholes` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 101.5 MB | compiled: the frozen backend exits (No module named 'py_vollib'); UniFMU then aborts the importer (rep.rs:168 panic, [§13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)) |
| `windpowerlib.wind_speed:logarithmic_profile` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 101.5 MB |  |

## Round 3 (tested-models-round3.md)

| Model | FMI | init | init --probe | build + simulate (per config) | compile (pyinstaller) + simulate | First error |
|---|---|---|---|---|---|---|
| `anastruct:SystemElements` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 52.5 MB | TypeError: buckling_factor is None |
| `antropy:perm_entropy` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 105.7 MB |  |
| `astropy.cosmology:FlatLambdaCDM` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 37.7 MB |  |
| `Bio.SeqUtils:gc_fraction` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 29.8 MB |  |
| `blackscholes:BlackScholesCall` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.7 MB |  |
| `commpy.modulation:QAMModem` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 78.2 MB | TypeError: y is an array of shape [2], not a single value: give it dimensions = [2] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `electricpy:powerset` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 71.2 MB |  |
| `haversine:haversine` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.6 MB |  |
| `heartpy:process` | 2 → 3 | ✓ | ✗ | plain build ✓, sim ✗ | plain: build ✓, sim ✗, 74.7 MB | FMI 2: fmugen: error: [model] constants.hrdata = call:heartpy:get_data("data.csv") fails: FileNotFoundError: data.csv not found. — FMI 3: fmugen: error: [model] constants.hrdata = call:heartpy:get_data("data.csv") fails: FileNotFoundError: data.csv not found. |
| `librosa:hz_to_mel` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 108.5 MB |  |
| `mendeleev:element` | 2 | ✓ | ✗ | plain ✓ | plain: build ✓, sim ✗, 41.5 MB | NotImplementedError: <built-in function getitem> |
| `meteocalc:heat_index` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.6 MB |  |
| `nashpy:Game` | 2 → 3 | ✗ | ✗ |  | — | FMI 2: fmugen: error: Game has no method 'is_zero_sum' — FMI 3: fmugen: error: Game has no method 'is_zero_sum' |
| `numpy_financial:pmt` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.7 MB |  |
| `numdifftools:Derivative` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.3 MB |  |
| `obspy.geodetics:gps2dist_azimuth` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 77.0 MB |  |
| `openap:Thrust` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 66.5 MB | compiled: the frozen backend exits (openap/data/aircraft/_synonym.csv missing); UniFMU then aborts the importer (rep.rs:168 panic, [§13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)) |
| `cv2:KalmanFilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 66.3 MB |  |
| `openturns:Normal` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 79.9 MB | TypeError: Wrong number or type of arguments for overloaded function 'new_Normal'. |
| `pedon:Genuchten` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 83.7 MB |  |
| `PyCO2SYS:sys` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.8 MB | TypeError: float() argument must be a string or a real number, not 'dict' |
| `pyfluids:Fluid` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 29.4 MB | ValueError: Invalid or not defined state! |
| `pygfunction.heat_transfer:finite_line_source` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.8 MB |  |
| `pykalman:KalmanFilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.5 MB |  |
| `pyloudnorm:Meter` | 2 | ✓ | ✓ | plain ✓ / probe build ✓, sim ✗ | plain: ✓, 53.2 MB | ValueError: blockwise_loudness has 0 values, expected 17 |
| `pymap3d:geodetic2enu` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.7 MB | TypeError: y is a tuple of shape [3], not a single value: give it dimensions = [3] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pymunk:Space` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 26.3 MB |  |
| `pyorbital.astronomy:sun_zenith_angle` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 25.0 MB |  |
| `pyquaternion:Quaternion` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 24.6 MB | FMI 2: ValueError: Unexpected number of elements in sequence. Got: 2, Expected: 4. — FMI 3: ValueError: Unexpected number of elements in sequence. Got: 2, Expected: 4. |
| `pyteomics.mass:calculate_mass` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 28.4 MB |  |
| `pythermalcomfort.models:pmv_ppd_iso` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 97.0 MB | TypeError: tsv is a string ('Neutral'), not a Real: set type = "String" for it in the config |
| `pywt:dwt` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 25.2 MB | TypeError: y0 is an array of shape [9], not a single value: give it dimensions = [9] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `pyxirr:npv` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 25.0 MB |  |
| `quantecon:LinearStateSpace` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 98.8 MB |  |
| `QuantLib:blackFormula` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 37.2 MB |  |
| `radioactivedecay:Inventory` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: build ✓, sim ✗, 88.8 MB | TypeError: float() argument must be a string or a real number, not 'Inventory' |
| `rainflow:count_cycles` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.6 MB | TypeError: y is a list of shape [4], not a single value: give it dimensions = [4] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `rdkit.Chem.Descriptors:MolWt` | 2 | ✓ | ✓ | plain ✗ / probe ✓ | probe: ✓, 44.7 MB | fmugen: error: the config defines no FMU variables: add [inputs]/[parameters] and [outputs] (the model's arguments and results could not be inferred) |
| `scipy.signal:lfilter` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 53.2 MB |  |
| `shapely:Point` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 26.2 MB |  |
| `simpy:Environment` | 2 → 3 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: build ✓, sim ✗, 24.7 MB | FMI 2: ValueError: until (1.0) must be greater than the current simulation time — FMI 3: ValueError: until (1.0) must be greater than the current simulation time |
| `skfuzzy:interp_membership` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.3 MB |  |
| `skimage.color:rgb2hsv` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 52.8 MB |  |
| `statsmodels.stats.proportion:proportion_confint` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 71.3 MB |  |
| `tellurium:loada` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: build ✓, sim ✗, 129.4 MB | compiled: the frozen backend exits (antimony missing); UniFMU then aborts the importer (rep.rs:168 panic, [§13](unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)) |
| `thermofeel:calculate_heat_index_simplified` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.7 MB | ValueError: Calling nonzero on 0d arrays is not allowed. Use np.atleast_1d(scalar).nonzero() instead. If the context of this error is of the form `arr[nonzero(cond)]`, just use `arr[cond]`. |
| `timezonefinder:TimezoneFinder` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 58.0 MB |  |
| `tmm:coh_tmm` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.6 MB | TypeError: kz_list is an array of shape [3], not a single value: give it dimensions = [3] (FMI 3) or read one element (from = "...:0"); fmugen init --probe finds them |
| `transforms3d.euler:euler2quat` | 2 | ✓ | ✓ | plain ✓ / probe ✓ | probe: ✓, 24.7 MB |  |
| `uncertainties:ufloat` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe ✓ | probe: ✓, 24.7 MB | TypeError: can't convert an affine function (<class 'uncertainties.core.Variable'>) to float; use x.nominal_value |
