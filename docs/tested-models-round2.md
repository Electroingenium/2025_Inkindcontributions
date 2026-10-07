# Tested models, round 2: 30 more published models

30 published, unmodified models, each from a library or domain not covered in [tested-models.md](tested-models.md). Each was run through `fmugen init` → `fmugen build --capture-output` → `fmpy validate` → `fmpy simulate`, for **FMI 2 and FMI 3**. Errors were **recorded, not fixed**. No fmugen code was changed.

Setup: Windows 11, Python 3.13 venvs made with `uv`, fmugen from this checkout (editable), FMPy. Date: 2026-10-06.

## Summary

| | Count |
|---|---|
| Models tried | 30 (from 30 libraries) |
| Pass with `init` alone, both FMI versions | **12**: 10 match a direct call exactly; astral and roboticstoolbox run, with caveats |
| Run, but the FMU is not useful (no outputs, or not the result that matters) | 5, of which PyTCI and cantera work with a hand-written config |
| Fail with the config `init` writes, pass with a hand-written config | 3: metpy, pysolar, ppigrf (FMI 3 only) |
| Fail, no working config found | 10 |

**Main problems found** (details [below](#problems-found)). Status as of 2026-10-07: 2, 3, 5 and 6 are fixed; 1 and 7 are UniFMU limitations (noted, not fixed in fmugen); 4 is open. The table above is from the first run; see [Rerun after the fixes](#rerun-after-the-fixes-2026-10-07) for the results with the fixes.

1. *(UniFMU limitation, not fixed)* **After an FMU error, the UniFMU Python backend keeps running.** FMPy reports the error and exits, but the backend (`main.py`, 2 processes) stays alive, holding the importer's stdout/stderr. Anything that reads that output (a pipe, `subprocess.run(capture_output=True)`, `… | grep`) then hangs. 31 orphaned backend pairs had built up by the end of these runs. A successful run leaves none behind. Seen with FMI 2 and FMI 3.
2. *(Fixed)* **`init` writes configs that `build` or the runtime then reject.** Dotted names from `--start a.b=…` become parameters that `build` refuses (simglucose). String attributes found in the code are typed Real (thermo). A date-time argument becomes `when = { start = 0.0 }` (pysolar, ppigrf). Constructor `*args` get passed as keyword arguments (python-control).
3. *(Fixed)* **Silent zero-output FMUs.** No warning when `init` finds no outputs (ambiance, PyTCI, cantera, pandapower).
4. *(Detected by `init --probe`; the runtime still fails on them)* **Outputs whose type or size changes at run time fail the step.** Complex arrays (impedance), arrays whose length varies (seirsplus), a property that is `None` (pyproj), an attribute that only exists sometimes (river).
5. *(Fixed)* **`to = "pos:N"` on constructor parameters is accepted by `build` but ignored at run time.** The constructor gets no arguments.
6. *(Fixed)* **`call:` start values can't use lazily exported submodules**, e.g. `pybamm.lithium_ion:SPM()`. The real module path works.
7. *(UniFMU limitation, not fixed)* **`fmpy simulate` shows no reason for a failure**, only `fmi3ExitInitializationMode failed with status 3`. The Python traceback is only visible with `simulate_fmu(debug_logging=True, logger=…)`. `--fmi-logging` instantiates with `loggingOn=False` and doesn't show it.

## Rerun after the fixes (2026-10-07)

The same 30 models, rerun with fmugen at `b437621` (fixes for problems 2, 3, 5 and 6) and the same `init` options as the tables below, in FMI 2 and FMI 3. Only `init` configs were rerun; the hand configs (PyTCI, cantera, metpy) were not. The tables further down are the original run of 2026-10-06 and are kept as they were.

| | 2026-10-06 | 2026-10-07 |
|---|---|---|
| Pass with `init` alone, both FMI versions | 12 | **17** |
| Run, but the FMU is not useful | 5 | 7 |
| Fail | 13 | 6 |

**Newly pass with `init` alone:**

| Model | `init` options (changes from the tables below) | FMI 2 | FMI 3 | Check |
|---|---|---|---|---|
| `pysolar.solar:get_altitude` | `--probe` | ✓ | ✓ | The epoch is set to UTC automatically, since the probe failed without a time zone. |
| `ppigrf:igrf` | `--probe` | ✓ | ✓ | B = (281.65, 25784.81, −36995.52) nT for today's date. FMI 2 now works too (1-element array outputs). |
| `control:StateSpace` | unchanged | ✓ | ✓ | A–D become `to = "pos:N"` parameters; y = (0, −2) = A·x. |
| `simglucose…:T1DPatient` | `--start=action=call:simglucose.patient.t1dpatient:Action(CHO=0.0, insulin=0.02)` | ✓ | ✓ | Gsub = 118.05. The dotted `--start action.CHO=…` now stops with an error that suggests this form. |
| `pyproj:Transformer` | unchanged | ✓ | ✓ | (440598.08, 4472390.03) out; `remarks` and `scope` commented out with a warning. |

**Unchanged passes:** gsw, py_vollib, windpowerlib, erfa, colour, hplib, pymsis, neurokit2, pyromat, astral and roboticstoolbox give the same values as on 2026-10-06. skops-digits passes in FMI 3 (predicts 0). In FMI 2, `fmpy simulate` exits 0, but `simulate_fmu(…, debug_logging=True, logger=…)` crashes FMPy with `OSError: access violation` (reproduced twice, and also without the String parameter `ensure_native_byte_order`). Not investigated.

**Build and run, but not useful (now with warnings):**
- **No outputs**: ambiance, pandapower, PyTCI, cantera and river all print `no outputs found: add [outputs] by hand`.
- **impedance** runs. The complex result is commented out as `y_real` / `y_imag`.
- **pybamm**: `call:pybamm.lithium_ion:SPM()` now works (problem 6). The voltage still can't be expressed as an output.

**Still fail:**

| Model | Error now |
|---|---|
| thermo (no `--probe`) | `CAS is a string (...): set type = "String"`. `init` now warns that the types of 114 outputs are guesses. |
| metpy | Needs pint units (`init` doesn't recognise `@check_units`). The hand config was not rerun. |
| pyet | Only accepts pandas Series with a date index (a limit of the library). |
| seirsplus | The arrays whose size changes are now commented out. It then fails in `doStep` inside seirsplus: `ValueError: Values in t_eval are not within t_span`. Not investigated. |
| mesa | `init` still crashes in `isolated_imports` (`KeyError: 'scipy._external'` / `'mesa.examples.advanced'`). |
| sgp4 | Still the misleading `--start names that are not arguments of the model` for C built-ins. |

Problem 1 is unchanged: 14 orphaned `main.py` backends built up during the rerun, and one held a lock on a work folder until killed.

## Results (2026-10-06)

Legend: ✓ = build, validate and simulate pass. ✗ = a step fails. "= direct" means the FMU's outputs equal a direct call of the model with the same inputs.

### Pass with `init` alone

| # | Domain | Model | `init` options | FMI 2 | FMI 3 | Check |
|---|---|---|---|---|---|---|
| 1 | Oceanography (TEOS-10) | `gsw:rho` | `--start SA=35.0 --start CT=10.0 --start p=1000.0` | ✓ | ✓ | 1031.281 kg/m³ = direct |
| 2 | Finance | `py_vollib.black_scholes:black_scholes` | `--start flag=c --start S=100.0 --start K=90.0 --start t=0.5 --start r=0.01 --start sigma=0.2` (string argument `flag`) | ✓ | ✓ | 12.1116 = direct |
| 3 | Wind energy | `windpowerlib.wind_speed:logarithmic_profile` | `--start wind_speed=5.0 --start wind_speed_height=10.0 --start hub_height=100.0 --start roughness_length=0.15` | ✓ | ✓ | 7.7414 m/s = direct |
| 4 | Astronomy (C extension) | `erfa:gmst06` | `--start uta=2460000.5 --start utb=0.25 --start tta=2460000.5 --start ttb=0.2508` | ✓ | ✓ | 4.27341 rad = direct |
| 5 | Color science | `colour.temperature:CCT_to_xy_CIE_D` | `--start CCT=6504.0 --probe` | ✓ | ✓ (array `[2]`) | xy = (0.31271, 0.32912) = direct (D65) |
| 6 | Heat pumps (buildings) | `hplib.hplib:HeatPump` | `--call simulate --probe "--start=parameters=call:hplib.hplib:get_parameters(model='Generic', group_id=1, t_in=-7, t_out=52, p_th=10000)" --start t_in_primary=-7.0 --start t_in_secondary=30.0 --start t_amb=-7.0` (DataFrame constructor argument, dict result) | ✓ | ✓ | all 8 dict outputs = direct (COP 2.902, P_th 16497 W) |
| 7 | Upper atmosphere (Fortran) | `pymsis:calculate` | `--probe --start dates=2024-01-01T00:00 --start lons=-3.7 --start lats=40.4 --start alts=400.0` | ✓ | ✓ (array `[1, 11]`) | = direct |
| 8 | Biomedical signals | `neurokit2:ecg_simulate` | `--start duration=1 --start sampling_rate=100 --start heart_rate=70 --start random_state=42 --probe` | ✓ (*) | ✓ | 100 samples = direct |
| 9 | Machine learning (Hugging Face) | `joblib:load` with model [`julien-c/skops-digits`](https://huggingface.co/julien-c/skops-digits) | `--call predict --probe "--start=filename=call:huggingface_hub:hf_hub_download(repo_id='julien-c/skops-digits', filename='sklearn_model.joblib')" "--start=X=[[…64 pixels of digit 0…]]"` (factory function, Int64 array output) | ✓ | ✓ | predicts 0, correct |
| 10 | Gas properties | `pyromat:get` | `--call cp --probe --start idstr=ig.N2 --start T=300.0` (factory function) | ✓ | ✓ | cp(N₂, 300 K) = 1.0397 kJ/kg/K = direct |
| 11 | Satellite/solar geometry | `astral.sun:elevation` | `--start observer.latitude=40.4 --start observer.longitude=-3.7 --probe` (dataclass argument split into fields) | ✓ | ✓ | runs, but see [astral](#astral-uses-the-wall-clock) |
| 12 | Robotics | `roboticstoolbox.models.DH:Panda` | `--call fkine --probe "--start=q=[0.0, -0.3, 0.0, -2.2, 0.0, 2.0, 0.785]"` | ✓ | ✓ | runs, but see [roboticstoolbox](#roboticstoolbox-the-result-of-the-call-is-dropped) |

(*) neurokit2 FMI 2: the first `fmpy simulate` ran while two other batches were running and exited non-zero with no message. 3 reruns passed. Not reproduced.

### Run, but the FMU is not useful

| # | Domain | Model | `init` options | FMI 2 | FMI 3 | Problem |
|---|---|---|---|---|---|---|
| 13 | Standard atmosphere | `ambiance:Atmosphere` | `--kind function --start h=1000.0`, with or without `--probe` | ✓ | ✓ | **No outputs.** All results are properties returning 1-element numpy arrays (`temperature`, `pressure`, …). None are written, and there is no warning. |
| 14 | Power systems | `pandapower:runpp` | `--probe "--start=net=call:pandapower.networks:example_simple()"` | ✓ | ✓ | **No outputs.** `runpp` returns `None` and writes into `net.res_bus` etc. (DataFrames). 15 solver options become inputs. No warning. (The first run timed out at 120 s while other batches ran; it passed with a longer timeout.) |
| 15 | Batteries | `pybamm:Simulation` | `--call step --probe "--start=model=call:pybamm.models.full_battery_models.lithium_ion:SPM()" --start dt=100.0` | ✓ | ✓ | The only output is `variables_returned` (Boolean). The voltage is `solution["Voltage [V]"].entries[-1]`, which a config can't express. With `call:pybamm.lithium_ion:SPM()` (the documented public path), the probe fails: `ModuleNotFoundError: No module named 'pybamm.lithium_ion'`, because it is a lazily set attribute, not a submodule. |
| 16 | Pharmacokinetics | `PyTCI.models.propofol:Marsh` | `--call wait_time --start weight=70.0 --start time_seconds=1`, with or without `--probe` | ✓ | ✓ | **No outputs.** The compartment concentrations `x1, x2, x3, xeo` are assigned in a nested function inside `wait_time` (not seen in the code), and stay 0 in the probe (no drug given). Works with a [hand config](#pytci-hand-config). |
| 17 | Combustion (C++ extension) | `cantera:Solution` | `--call equilibrate --probe --start infile=gri30.yaml --start XY=HP` | ✓ | ✓ | **No outputs.** Cantera's state (`T`, `P`, `density`, …) are Cython properties, which `init` doesn't list. Works with a [hand config](#cantera-hand-config). |

### Fail with `init`'s config, pass by hand

| # | Domain | Model | What `init` wrote | Error | Hand config |
|---|---|---|---|---|---|
| 18 | Meteorology | `metpy.calc:dewpoint_from_relative_humidity` | plain Real inputs (metpy needs pint quantities; its `@check_units` decorator isn't recognised) | metpy raises `ValueError` (needs units) at initialization: `fmi2/3ExitInitializationMode failed with status 3` (and the backend is left running, see above). | `convert = "pint"` with `unit = "degC"` / `"dimensionless"`: ✓ ✓, 13.843 °C = direct (metpy's own registry; it works) |
| 19 | Solar position | `pysolar.solar:get_altitude` | `when = { start = 0.0 }` (unannotated date-time argument; the probe fails silently) | `fmi2/3ExitInitializationMode failed` | `[time] when = { source = "end_time", epoch = "2026-06-21T06:00:00+00:00" }`: ✓ ✓, 56.7357° at 10:00 UTC = direct |
| 20 | Solar position | `astral.sun:elevation` (as #11, with a fixed date) | — | — | `[time] dateandtime = {…same…}`: ✓ ✓, 56.7319° = direct |
| 21 | Geomagnetism | `ppigrf:igrf` | `date = { start = 0.0 }`, and scalar outputs `y0, y1, y2` (from the code: the probe failed on the date) | `fmi2/3ExitInitializationMode failed`. By hand with `[time]`: `TypeError: only 0-dimensional arrays can be converted to Python scalars` (results are 1-element arrays). With a timezone-aware epoch, ppigrf itself fails (`can't compare offset-naive and offset-aware datetimes`). | FMI 3, naive epoch, outputs with `dimensions = [1]`: ✓, B = (263.75, 25781.19, −36988.82) nT = direct. FMI 2: no config possible (array result). |
| 22 | Pharmacokinetics | `PyTCI…:Marsh` (#16) | — | — | ✓ ✓, see [below](#pytci-hand-config) |
| 23 | Combustion | `cantera:Solution` (#17) | — | — | ✓ ✓, adiabatic CH₄/air flame 2225.52 K = direct |
| 24 | Machine learning | `joblib:load` + [`nateraw/iris-svc`](https://huggingface.co/nateraw/iris-svc) | — | `init` exits: `--start names that are not arguments of the model: ['X']`. The real cause is that the pickle can't be loaded (`module '__main__' has no attribute 'SVC'`, the model is broken as published), but **the message says nothing about the load failure.** | replaced by `skops-digits` (#9) |

### Fail, no working config found

| # | Domain | Model | `init` options | Stage | Error |
|---|---|---|---|---|---|
| 25 | Chemistry | `thermo:Chemical` | `--kind function --start ID=water --start T=350.0 --start P=101325.0` (no `--probe`) | init of the FMU | `ValueError: could not convert string to float: '7732-18-5'`. `init` lists `CAS`, `name`, `formula`, `smiles`, … as outputs **without `type = "String"`**. It also writes a `globals` list of 13 module variables. |
| 26 | Hydrology | `pyet:pm_fao56` | `--start tmean=20.0 --start wind=2.0 --start rs=20.0 --start rh=60.0 --start elevation=100.0 --start lat=0.7` | init of the FMU | `AttributeError: 'float' object has no attribute 'index'`. pyet only accepts pandas Series with a date index. That's a limit of the library, but `init` gives no hint. |
| 27 | Epidemiology | `seirsplus.models:SEIRSModel` | `--call run_epoch --probe --start initN=100000 --start beta=0.147 --start sigma=0.192 --start gamma=0.0714 --start initI=100 --start runtime=1.0` | init of the FMU | `ValueError: tseries has 1 values, expected 2`. The probe sized the history arrays (`tseries`, `numS`, …) from one call, but they grow (or vary) on every call. |
| 28 | Geodesy | `pyproj:Transformer` | `--create from_crs --call transform --probe --start crs_from=EPSG:4326 --start crs_to=EPSG:25830 --start always_xy=true --start xx=-3.7 --start yy=40.4` | first step | `TypeError: remarks is None`. A String property that is `None` fails the whole step. |
| 29 | Online ML | `river.linear_model:LinearRegression` | `--call learn_one --probe "--start=x={'a': 1.0, 'b': 2.0}" --start y=3.0` | first step | `LookupError: max_cum_l1: cannot read attribute 'max_cum_l1'`. The probe saw an attribute that isn't there at the FMU's first step. |
| 30 | Electrochemistry | `impedance.models.circuits:Randles` | `--call predict --probe "--start=initial_guess=[0.01, 0.005, 0.001, 200.0, 0.1]" "--start=frequencies=[1.0, 10.0, 100.0, 1000.0]"` | first step | `TypeError: only 0-dimensional arrays can be converted to Python scalars`. `predict` returns a **complex** array. `init` writes `y = { from = "return" }`, a scalar, with no comment. |
| 31 | Control | `control:StateSpace` | `--call dynamics --probe "--start=A=[[0.0, 1.0], [-2.0, -0.5]]" "--start=B=[[0.0], [1.0]]" "--start=C=[[1.0, 0.0]]" "--start=D=[[0.0]]" --start t=0.0 "--start=x=[1.0, 0.0]" "--start=u=[0.0]"` | init of the FMU | `TypeError: Expected 1, 4, or 5 arguments; received 0.` The constructor is `StateSpace(*args, **kwargs)`. `init` passes A–D "through **kwargs". By hand with `to = "pos:0"`…`"pos:3"` on the parameters, **`build` accepts it, but the constructor still gets 0 arguments**. |
| 32 | Agent-based | `mesa.examples:BoltzmannWealth` | `--call step --probe` | `init` crashes | `KeyError: 'scipy'` from `importlib` `_get_parent_path`, inside `isolated_imports` (`src/fmugen/__main__.py:131`) on exit. |
| 33 | Orbital mechanics (C extension) | `sgp4.api:Satrec` | `--create twoline2rv --call sgp4 --probe --start line1=… --start line2=… --start jd=2458826.5 --start fr=0.8625` | `init` exits | `--start names that are not arguments of the model: ['fr', 'jd', 'line1', 'line2']`. Built-in methods have no inspectable signature. No hint to write the config by hand (as the CoolProp docs suggest). |
| 34 | Medical (T1D glucose) | `simglucose.patient.t1dpatient:T1DPatient` | `--create withName --call step --probe --start name=adolescent#001 --start action.CHO=0.0 --start action.insulin=0.02` | `build` | `init` succeeds but writes `"action.CHO"` and `"action.insulin"` as **parameters** (constructor `**kwargs`), and `action = { start = 0.0 }` as an input. `build` then rejects them: `[parameters] action.CHO: variable names must be valid Python identifiers`. The probe failed: `action: no default and no class annotation to build it from ['CHO', 'insulin']` (`Action` is a namedtuple). |

Rows 20, 22 and 23 repeat models from earlier rows, and 24 is a replaced model, so there are 30 distinct models: 1–19, 21 and 25–34.

---

## Problems found

### The backend outlives a failed FMU

Every FMU that failed in `exitInitializationMode` or `doStep` left its UniFMU backend running: `venv\Scripts\python.exe main.py` and the base `python.exe main.py` it starts. FMPy itself exits with the error, but whoever reads FMPy's stdout/stderr through a pipe waits for the backend, which never exits. This first looked like an FMI 2 hang on metpy (my first test driver used pipes). With output going to files, metpy fails cleanly in both FMI versions. Reproduce: `fmpy simulate pyproj_tf.fmu 2>&1 | Out-Null` in PowerShell never returns, and the `main.py` process count goes up by 2. A passing FMU (gsw) leaves no process behind. Probably `fmi2FreeInstance` / `fmi3FreeInstance` isn't reached, or doesn't stop the backend, after an error status.

**Status:** a UniFMU limitation (the backend process is managed by UniFMU, not fmugen); not fixed here. Workaround: send the importer's output to a file, not a pipe.

### Failure messages

`fmpy simulate` only prints the failed FMI call. The Python traceback (e.g. thermo's `ValueError: could not convert string to float: '7732-18-5'` from `fmugen_runtime.coerce`) shows with `fmpy.simulate_fmu(…, debug_logging=True, logger=print)`. The errors in this report were also read by running the FMU's `fmugen_runtime.make_engine` in-process.

**Status:** a UniFMU limitation, not fixed. fmugen already sends the full traceback to the FMI log, but UniFMU drops log messages when the importer instantiates with `loggingOn=False`, which FMPy's CLI does. Workaround: `fmpy.simulate_fmu(…, debug_logging=True, logger=print)`.

### `init` writes configs that fail later

- **Dotted `--start` names** (`action.CHO`) for an argument with no default and no annotation become constructor `**kwargs` parameters, which `build` rejects (simglucose).
- **String outputs typed Real**: thermo's `CAS`, `name`, `formula`… are read from the code without a type (no `--probe`).
- **Unannotated date-time arguments** get `start = 0.0`, with no hint about `[time] … epoch` (pysolar, ppigrf). The probe fails and the failure is only visible as "not seen in the probe" comments.
- **`*args` constructors** get their `--start` values as keyword arguments (python-control).

**Fixed (2026-10-07):**
- `ARG.FIELD` starts go to the argument's function and are never `**kwargs` parameters. Namedtuple arguments are split into fields like dataclasses. When the class of `ARG` can't be known, `init` stops with an error that says so and suggests `--start=ARG=call:module:Class(...)`. simglucose works that way (`Action(CHO=0.0, insulin=0.02)`, a constant).
- A numeric output that gets a string at run time fails with `NAME is a string (...): set type = "String" for it in the config`. Without `--probe`, `init` warns that output types were read from the code.
- Date-time arguments (annotated `datetime`, or named `when`, `date`, `dateandtime`, …) get `[time] NAME = { source = "end_time", epoch = "<today>T00:00:00" }`. The epoch is naive, and `--probe` switches to UTC when the model needs a time zone. pysolar (UTC), ppigrf (naive, FMI 3) and astral now run with `init` alone.
- A constructor that only takes `(*args, **kwargs)` gets the extra `--start` values as `to = "pos:N"` parameters, in the order given. python-control `StateSpace` now runs with `init` alone (y = A·x checked).

### Silent outputs problems

- FMUs with **no outputs** build without a warning: `ambiance` (properties returning 1-element arrays), PyTCI (state in a nested function), cantera (Cython properties), pandapower (results in DataFrames on the argument).
- **Complex results** (impedance) are written as a scalar Real output.
- **Arrays whose size changes** between calls (seirsplus history) get a fixed size from the probe.
- An output that is **`None`** at run time (pyproj `remarks`) fails the step.

**Fixed (2026-10-07):** zero outputs only. `init` warns (stderr and a comment in `[outputs]`), and `build` prints `note: the FMU has no outputs`.

**Detected (2026-10-07), problem 4:** `init --probe` now writes these commented out, with the reason, and warns on stderr:

- a **complex** value: two commented lines for its parts, `y_real = { from = "return:real", … }` and `y_imag`. Uncommented, the impedance FMU's outputs equal a direct `predict` call.
- a value or property that is **`None`** (or raised) in the probe, although the code annotates it as a number, bool or string (pyproj `remarks`, `scope`).
- an **array whose size changes**: classes are stepped a second time, and arrays whose size differs are commented out (seirsplus `tseries`, `numS`, … went from 2 to 3).
- an output found **only in the code** that the probe's working call didn't set or return. river's `max_cum_l1` is in this group: it is set only when `l1 != 0`, and the probe never saw it (the table above is wrong to say it did).

The runtime is unchanged: an output that does turn into `None`, changes size or is missing still fails the step.

### `to = "pos:N"` on constructor parameters is ignored

Accepted by `build`, but the constructor of `control.StateSpace` is still called with no positional arguments.

**Fixed (2026-10-07):** in a class's `[parameters]`, `to = "pos:N"` is a constructor position (numbered separately from the step call's).

### `call:` can't reach lazily exported names

`call:pybamm.lithium_ion:SPM()` fails (`No module named 'pybamm.lithium_ion'`), even though `pybamm.lithium_ion.SPM` is the public path. `pybamm.models.full_battery_models.lithium_ion:SPM()` works.

**Fixed (2026-10-07):** when `module` in `module:name` isn't an importable submodule, it is reached as attributes of the longest importable prefix. `call:pybamm.lithium_ion:SPM()` now works.

### `init` crash in `isolated_imports`

`fmugen init mesa.examples:BoltzmannWealth …` crashes with `KeyError: 'scipy'` from `importlib._bootstrap_external._get_parent_path`, when `isolated_imports` restores `sys.modules` (`src/fmugen/__main__.py:131`).

### Misleading `init` error when the model can't be loaded

For a factory (`joblib:load`) whose result can't be built, `init` reports `--start names that are not arguments of the model: ['X']` instead of the load error. Same message for C built-ins with no signature (sgp4).

### `to = "call:…"` setters run once more than the steps

PyTCI's `give_drug(mg)` adds a bolus each time it's called. Bound with `to = "call:give_drug"`, it runs at initialization and before every step: 60 steps give 61 doses. The FMU matches exactly `give_drug` once, then 60 × (`give_drug`, `wait_time(1)`). That's harmless for setters that store a value (TCLab's `Q1`), but not for ones that accumulate.

### astral uses the wall clock

`astral.sun:elevation(observer, dateandtime=None)` uses the current time when `dateandtime` is `None`. `init` keeps it at `None`, so the FMU's output depends on when it runs, and doesn't follow simulation time. `dateandtime` is annotated `Optional[datetime]`, but `init` doesn't suggest the `[time] … epoch` binding.

### roboticstoolbox: the result of the call is dropped

`Panda.fkine(q)` returns an `SE3` pose (a 4×4 matrix in `.A`). `init --probe` doesn't output it. Instead, it writes 30+ constant properties of the robot (`a`, `d`, `qlim`, `name`, `manufacturer`, …) as outputs. It also writes a long `save_state` list, since the object can't be pickled.

---

## Hand configs

### PyTCI hand config

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

Simulated for 60 s with a 1 s step: x1 = 6.6654, xeo = 0.8613, identical to the direct sequence above, in FMI 2 and FMI 3. Note that the model advances by `time_seconds`, not by the FMI step size: with FMPy's default 0.1 s step, the model ran 10× faster than simulation time.

### Cantera hand config

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

T = 2225.5246 K, ρ = 0.150194 kg/m³, M = 27.4286, equal to a direct `equilibrate('HP')` to 1e-11 relative. The fuel/air state can only be set in `setup`: Cantera's `TPX` is a tuple property, and there is no way to bind inputs to it.

### metpy hand config

```toml
[inputs]
temperature = { start = 25.0, unit = "degC", convert = "pint" }
relative_humidity = { start = 0.5, unit = "dimensionless", convert = "pint" }

[outputs]
y = { from = "return", unit = "degC" }
```

---

## Environment notes (not fmugen bugs)

- **Windows long paths:** cantera and pybamm (`idaklu`) failed to import from a venv in a deep temp folder (`DLL load failed … nombre del archivo o la extensión es demasiado largo`). The same packages work from a venv in `%LOCALAPPDATA%\Temp\ctv`. Users building FMUs from deeply nested project folders may hit this, since the FMU runs with the build venv.
- **Broken published models:** `nateraw/iris-svc` (pickled from `__main__`), `BenjaminB/plain-sklearn` (old sklearn module path) and `scikit-learn-examples/example` (custom class) can't be loaded with current scikit-learn, with or without fmugen.

## Versions

gsw, py_vollib, windpowerlib, pyerfa, colour-science, hplib, pymsis, neurokit2, joblib/scikit-learn (+ huggingface_hub), pyromat, astral, roboticstoolbox-python 1.4.4, ambiance, pandapower, pybamm 26.9, PyTCI 1.1, cantera 3.2.0, metpy, pysolar, ppigrf (IGRF-14), thermo, pyet, seirsplus, pyproj, river, impedance, python-control, mesa 3.5.1, sgp4, simglucose. All are the latest versions on PyPI on 2026-10-06, on Python 3.13.
