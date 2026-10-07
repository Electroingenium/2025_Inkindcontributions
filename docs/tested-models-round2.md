# Tested models, round 2: 30 more published models

30 published, unmodified models, each from a library or domain not covered in [tested-models.md](tested-models.md). Each was run through `fmugen init` → `fmugen build --capture-output` → `fmpy validate` → `fmpy simulate`, for **FMI 2 and FMI 3**. Errors were **recorded, not fixed**. No fmugen code was changed.

Setup: Windows 11, Python 3.13 venvs made with `uv`, fmugen from this checkout (editable), FMPy. Date: 2026-10-06.

## Summary

**Main problems found** (details [below](#problems-found)). Status as of 2026-10-07: 2, 3, 5 and 6 are fixed; 1 and 7 are UniFMU limitations (noted, not fixed in fmugen); 4 is open.

1. *(UniFMU limitation, not fixed)* **After an FMU error, the UniFMU Python backend keeps running.** FMPy reports the error and exits, but the backend (`main.py`, 2 processes) stays alive, holding the importer's stdout/stderr. Anything that reads that output (a pipe, `subprocess.run(capture_output=True)`, `… | grep`) then hangs. 31 orphaned backend pairs had built up by the end of these runs. A successful run leaves none behind. Seen with FMI 2 and FMI 3.
2. *(Fixed)* **`init` writes configs that `build` or the runtime then reject.** Dotted names from `--start a.b=…` become parameters that `build` refuses (simglucose). String attributes found in the code are typed Real (thermo). A date-time argument becomes `when = { start = 0.0 }` (pysolar, ppigrf). Constructor `*args` get passed as keyword arguments (python-control).
3. *(Fixed)* **Silent zero-output FMUs.** No warning when `init` finds no outputs (ambiance, PyTCI, cantera, pandapower).
4. *(Detected by `init --probe`; the runtime still fails on them)* **Outputs whose type or size changes at run time fail the step.** Complex arrays (impedance), arrays whose length varies (seirsplus), a property that is `None` (pyproj), an attribute that only exists sometimes (river).
5. *(Fixed)* **`to = "pos:N"` on constructor parameters is accepted by `build` but ignored at run time.** The constructor gets no arguments.
6. *(Fixed)* **`call:` start values can't use lazily exported submodules**, e.g. `pybamm.lithium_ion:SPM()`. The real module path works.
7. *(UniFMU limitation, not fixed)* **`fmpy simulate` shows no reason for a failure**, only `fmi3ExitInitializationMode failed with status 3`. The Python traceback is only visible with `simulate_fmu(debug_logging=True, logger=…)`. `--fmi-logging` instantiates with `loggingOn=False` and doesn't show it.

## Rerun after the fixes (2026-10-07)

The same 30 models, rerun with fmugen at `b437621` (fixes for problems 2, 3, 5 and 6) and the same `init` options as the first run, in FMI 2 and FMI 3. Only `init` configs were rerun; the hand configs (PyTCI, cantera, metpy) were not.

| | 2026-10-06 | 2026-10-07 |
|---|---|---|
| Pass with `init` alone, both FMI versions | 12 | **17** |
| Run, but the FMU is not useful | 5 | 7 |
| Fail | 13 | 6 |

**Newly pass with `init` alone:**

| Model | `init` options (changes from the first run) | FMI 2 | FMI 3 | Check |
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
- an output found **only in the code** that the probe's working call didn't set or return. river's `max_cum_l1` is in this group: it is set only when `l1 != 0`, and the probe never saw it.

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
