# Tested models: GEKKO (2026-10-13)

10 published, unmodified models built on [GEKKO](https://github.com/BYU-PRISM/GEKKO) (dynamic optimization and simulation of DAE systems), run with fmugen at `da28d4e` (branch `bugfixing`). Each model went through:

1. `fmugen init` (code only)
2. `fmugen init --probe`
3. `fmugen build --capture-output` on each config `init` wrote, then `fmpy.simulate_fmu` for 3 s with 1 s outputs
4. `fmugen build --capture-output --compile nuitka` on the best config (the `--probe` one when it simulated), then the same simulation

All with FMI 2. Errors were **recorded, not fixed**: no fmugen code was changed.

Setup: Windows 11, Python 3.13, one uv venv for all 10 models, fmugen editable from this checkout, gekko 1.3.2 (local solver, `remote=False` unless the model says otherwise), Nuitka 4.3, FMPy 0.3.32, UniFMU 0.14, pandas 2.3.3 (see the CGE row), pythermalcomfort 2.10 (needforheat imports `pmv_ppd`, removed in 3.x).

## The models

| # | Model | Source | Entry given to `init` | `init` options |
|---|---|---|---|---|
| 1 | Ethanol fed-batch bioreactor (10 ODEs) | [APMonitor](https://apmonitor.com/do/index.php/Main/EthanolBioreactor), code block 1 | `ethanol_bioreactor.py` | none |
| 2 | Binary distillation column | [GEKKO `examples/distillation.py`](https://github.com/BYU-PRISM/GEKKO/blob/master/examples/distillation.py) | `distillation.py` | none |
| 3 | Distillation column as a Gym environment | [Kalpesh-RL/DistillationColumn](https://github.com/Kalpesh-RL/DistillationColumn) `f2b9966` | `DistColEnvDynInc_altrewards.py:DistColEnvDynInc` | `--start "Action=[0.0, 0.0, 0.0]" --setup reset` |
| 4 | Batch bioreactor (Monod growth) | [Bartosz1280/Bioreactor-modeling](https://github.com/Bartosz1280/Bioreactor-modeling) `3112aba` | `Bioreactor.py:SimpleBioreactor` | `--call solve`, `time_arr` (0–15 h, 151 points) and `simulation_input` (the repo notebook's first case) |
| 5 | Cell transmembrane potential | [0xDBFB7/transmembrane_potential](https://github.com/0xDBFB7/transmembrane_potential) `165c86f` | `transmembrane_lib.py:gekko_sim_method` | `--kind function` |
| 6 | Directional drilling MPC | [Xiang-Gu/CS394R_RL_Directional_Drilling](https://github.com/Xiang-Gu/CS394R_RL_Directional_Drilling) `12a45cf` | `mpc/mpc.py:solveMPC` | `--call action --start "state=[0.0, 0.0, 0.0, 0.0]"` |
| 7 | Nuclear-renewable hybrid energy system | [BYU-PRISM/NHES-opt-sensitivity](https://github.com/BYU-PRISM/NHES-opt-sensitivity) `5e9a6f2` | `simple_nhes.py:model` | `--start params=<the module's nom_params>` |
| 8 | Residential heat diagnosis | [energietransitie/needforheat-diagnosis-software](https://github.com/energietransitie/needforheat-diagnosis-software) `48d3a85` | `analysis/rhc_analysis.py:Model` | `--call building` |
| 9 | Heat exchanger network synthesis | [waikato-ahuora-smart-energy-systems/OpenHENS](https://github.com/waikato-ahuora-smart-energy-systems/OpenHENS) `5081bab` | `openhens:OpenHENS` (installed with `pip install -e`) | `--call solve`, the README's options (Four-stream case, `min_dT_list=[10]`, `min_dqda_list=[1, 2, 3]`, `max_parallel=2`, `best_solns_to_save=1`) |
| 10 | Computable general equilibrium economy | [konradarchicinski/cge_model_python](https://github.com/konradarchicinski/cge_model_python) `60d611d` | `Code/model.py:CGE` | `--call results --start capital=0.1 --start labour=0.0` (what its `main()` calls) |

1 and 2 are scripts that build and solve the model at module level; 3–10 are built around a class or function.

## Summary

| | Count |
|---|---|
| Models | 10 |
| `init` writes a config | 8 (not the two scripts) |
| `init --probe` writes a config | 8 |
| A config builds | 7 (CGE: module name clash) |
| **Simulates correctly** | **1** (distillation Gym environment, `--probe` config) |
| Simulates, but has no outputs | 1 (bioreactor) |
| `--compile nuitka` builds | **0 of 6 tried**: the same fmugen bug every time (problem 1) |

Of the 8 that don't simulate correctly, the cause is:

| Cause | Models |
|---|---|
| **fmugen** | bioreactor and CGE (no outputs found, problem 3, fixed); CGE also needs its `model.py` renamed (problem 2, intended) |
| The model is a script with no entry | ethanol, distillation |
| The model fails without fmugen too | ethanol (GEKKO's local solver crashes), transmembrane (`GEKKO` is never imported) |
| Inputs fmugen can't give | drilling MPC (needs an environment object), needforheat (pandas DataFrames of measurements) |
| Missing data or solver | NHES (`grid_data/more_data_scaled.csv` isn't in the repo), OpenHENS (needs the COIN-OR `couenne` binary on PATH) |

## Fixes after the run (2026-10-13)

Problems 1, 3 and 4 below were fixed the same day. Problem 2 is intended: fmugen asks to rename a file named `model.py`. The tables below still show the first run.

| Problem | Fix | Result |
|---|---|---|
| 1. Nuitka gets package options for single modules | `--include-package-data` only for packages, and `--include-module` instead of `--include-package` for a module ([distribute.py](../src/fmugen/distribute.py), `_nuitka_package_args`). A package is a name whose spec has a non-empty `submodule_search_locations`: six sets `__path__ = []` (for `six.moves`), and once imported during a build, its spec has an empty list, not `None`. The PyInstaller command is unchanged. | `examples/simple_pid` compiles with Nuitka and simulates (12 min, the slow test). The GEKKO models weren't compiled with Nuitka: with gekko and numpy, a build takes over 30 minutes here (see [Compiling](#compiling)). |
| 3. GEKKO results on the object not found | `init --probe` now makes an output of each public attribute holding a GEKKO result (a `Var`/`SV`/`CV`, an `Intermediate`, an `FV`/`MV`; not a `Param` or `Const`), and of each such value in a dict attribute (`self.W["HOU1"]` → `W.HOU1`). The output reads its value at the end of the time horizon: `from = "attr:X.value.-1"`. Dotted paths now take negative indexes (`.-1`); before a GEKKO variable's first solve, its value isn't a list, and reading it counts as missing (like an attribute not set yet). | Bioreactor: 5 outputs (`X`, `S`, `mu`, `dXdt`, `dSdt`); X goes from 0.0451 to 0.0444 g/L over 3 steps (X₀ + Y·S₀ − K_d·15 h = 0.045). CGE: 27 outputs. Built from a copy with `model.py` renamed, its first step gives the direct run's values (x3 supply 72.076, price 1.119). The distillation environment gets `D`, `B` and `FL` too (D = 1.133, B = 0.873). |
| 4. Raw traceback when importing a script fails | An exception (or `SystemExit`) raised by the model's top-level code during `init` or `build` becomes a `fmugen: error`, naming the model's line and where it was raised. | ethanol: `fmugen: error: importing …/ethanol_bioreactor.py failed: FileNotFoundError: … options.json (at ethanol_bioreactor.py:138, in gk_post_solve.py:13); importing a module runs its top-level code` |

Two more fixes, from the compile check below (2026-10-14):

| Problem | Fix | Result |
|---|---|---|
| A name both the constructor and the step method take could only reach the step method | `--start <method>_NAME=…` (the name `init` gives the method's variable) now goes to the step method, and then `--start NAME=…` to the constructor. With only `NAME`, nothing changes (on a tie, the step method); `<method>_NAME` was rejected before, so no command that worked behaves differently. | CFTOC: `--start x0=… --start calculate_optimal_actuation_x0=…` gives the constructor its `x0`/`Xm`; `init --probe` writes a config that needs no edits. |
| A failed compile hid its error | fmugen kept the last 4,000 characters of the compiler's output, which Nuitka filled with warnings (duplicate data files). Now warnings are left out, and the exit status is named, or that the output folder is missing. | |

Tests: `test_nuitka_gets_package_options_only_for_packages`, `test_gekko_results_kept_on_the_object_are_outputs` (needs gekko), `test_dotted_path_reads_the_last_element`, `test_model_that_fails_when_imported`. and a both-names case in `test_inference.py`'s shared-name test. The fast suite passes (150 passed, 9 skipped).

After the fixes, `init`, `build` and simulate were rerun on the 9 other models. Nothing else changed: the 7 model-side failures fail the same way, and CGE still stops at the rename.

## Compiling

After the Nuitka fix, the bioreactor's Nuitka build ran 69 minutes and failed with its error cut off (the second fix above), and the distillation environment's ran over 30 minutes without finishing; both were stopped. For the compile check, a lighter GEKKO model was used instead:

| Model | Source | Entry | Dependencies |
|---|---|---|---|
| Constrained finite-time optimal control (path following for a robot carrying a load with another) | [ollyme102b/ros_workspace](https://github.com/ollyme102b/ros_workspace) `03f5938`, `src/olly_control/src/v2/CFTOCSolverV2.py` | `CFTOCSolverV2.py:CFTOCSolverV2`, `--call calculate_optimal_actuation` | gekko, numpy |

Starts from the repo's test: A = I₃, B = 0.5·I₃, x0 = (−2, −7.5, 0), Xm the other robot's path over 10 steps from (−4, −8) at (0.01, 0.05) per 0.5 s, N = 10, umax = 0.1, l = 2, path constraint [4, 10, 80]; arrays passed with `--convert NAME=numpy`.

| | Result |
|---|---|
| `init --probe` | ✓ (with the shared-name fix; before it, the constructor's `x0`/`Xm` got a made-up `0.0` and the probe failed) |
| build + simulate | ✓ y = (−0.09546, −0.02481, 0), then (−0.09521, −0.02558, 0) twice: **the same as calling the class directly**, to all printed digits |
| `--compile pyinstaller` + simulate | ✓ **2 min, 43 MB**, same values, in a venv with only gekko, numpy, fmugen, PyInstaller and FMPy |
| `--compile nuitka` | not finished: stopped after 30 min |

In the shared venv of this test (with OpenHENS's and needforheat's dependencies installed), the same PyInstaller compile took 19 min and made a 195 MB FMU (489 MB unpacked: llvmlite, pyarrow, scipy, pandas, matplotlib, PIL). fmugen collects every gekko submodule, and `gekko.ML`, the Pyomo solver extension and `gekko.support` import scikit-learn, Pyomo and IPython inside `try:`: when those are installed, PyInstaller follows them. **Compile a model in a venv with only what it needs.**

## Replacements (2026-10-14)

The models that failed for reasons of their own were replaced, or reworked when the fix was small, and run through `init`, `init --probe`, build and simulate (FMI 2) with the fixes above. All 6 simulate with their `--probe` config.

| Replaces | Why | Model | Source | Entry and starts |
|---|---|---|---|---|
| distillation script | a script, nothing to call | **Distillation column, reworked into a class** (equations unchanged) | GEKKO `examples/distillation.py` | `distillation_column.py:DistillationColumn`, `--call step`: builds the model and solves its steady state in `__init__`, then `step(rr, dt)` runs `dt` minutes at reflux ratio `rr` from where the last step ended. Results are floats set by `step()`; local solver; no plots. |
| transmembrane | the library's GEKKO class is dead code | **Debutanizer column, steady state** (30 stages) | [Arushan45/Debutanizer-Project](https://github.com/Arushan45/Debutanizer-Project) `f6fe813` | `debutanizer.model:solve_steady_state`, installed with `pip install -e`; `--start reflux_ratio=2.5 --start alpha=1.9717789099` (the repo's calibrated α) |
| NHES | its input CSV isn't published (the FigShare collection holds only result pickles) | **Debutanizer reflux optimization** (minimum boil-up for 99.1% purity) | same | `debutanizer.model:optimize_reflux`, `--start alpha=1.9717789099` |
| drilling MPC | solves on APMonitor's server, not reachable from here | **Linear MPC** | [dhruvhaldar/apsis](https://github.com/dhruvhaldar/apsis) `a171cf1` | `apsis/mpc.py:solve_mpc`; the app's defaults: A = [[0, 1], [−1, −1]], B = [[0], [1]], Q = I, R = [[1]], x0 = (1, 0), N = 20, dt = 0.5, u ∈ [−1, 1] |
| needforheat | needs DataFrames of measured data | **2×2 FOPDT process** (a `GEKKO` subclass, one step per call) | [BYU-PRISM/Transformer_MPC](https://github.com/BYU-PRISM/Transformer_MPC) `7686735`, `02_Surrogate/FOPDT/MIMO/…/functions/process_fopdt.py` | `process_fopdt.py:ProcessModel`, `--call run --start "u=[1.0, 0.5]"` |
| OpenHENS | needs the COIN-OR couenne binary | **MPC controller for that process** (a `GEKKO` subclass) | same repo, `03_HybridModel/03_TCLab_PINN_Controllers/functions/mpc_gekko.py` | `mpc_gekko.py:MPCModel`, `--call solve` (GEKKO's own `solve`) |

| Model | init | init --probe | build + simulate | Check |
|---|---|---|---|---|
| Distillation class | ✓ | ✓ | plain ✓ / probe ✓ | 7 outputs. At reflux 3.0, the condenser goes 0.785721, 0.837391, 0.867374 and the reboiler 0.190012, 0.145341, 0.120733: **the script's own values** for its reflux step (GEKKO applies the script's change at t = 10 from t = 9). At 0.7 it stays at the steady state (0.6961 / 0.3039). |
| Debutanizer, steady state | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | Distillate C4 0.96999957519, vapor 133.0 kmol/h, duty 0.84972 MW: **the repo's `results/summary.json`** to all digits. Code-only: `c4_profile is a list of shape [30]` (known, problem 4 of the rerun; `--probe` finds it). |
| Debutanizer, optimization | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | Reflux 2.7602061381, purity 0.991, vapor 142.8878332478: the repo's optimum, to all digits. |
| Linear MPC | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | Returns (time, states, inputs) over the horizon: 21 + 42 + 21 outputs; time 0, 0.5, … 10. |
| FOPDT process | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | y = (0.3333, 0.0833), (0.6111, 0.1528), (0.8426, 0.2106) for u = (1, 0.5): K₁₁ = 2, K₂₂ = 1, τ = 5, 1 s steps with GEKKO's implicit scheme (2·(1 − 1/1.2) = 0.3333). Outputs `y1`, `y2`, `u1`, `u2` come from the GEKKO-results fix. |
| MPC controller | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | Runs, but with no setpoints given its moves stay near 0 (u ≈ 0.0002). The setpoints are attributes (`y1.SP`); an input bound to them (`to = "attr:y1.SP"`) would have to be added by hand. |

Two smaller findings:

- **A `GEKKO` subclass exposes GEKKO's own attributes.** For `ProcessModel` and `MPCModel`, the code-only config has `solver_options` (an empty list), which fails the step (`solver_options is a list of shape [0]`), and the `--probe` one has `csv_status` (a String output) and a commented-out `gui`. They're GEKKO's state, not the model's results. **Fixed (2026-10-14):** for a model class in the user's own files, what the code of an installed library base (GEKKO, a filterpy filter, …) sets on `self` isn't taken for a result: the code-only reading doesn't follow the base's methods (`self.solve()`), and the probe leaves the attributes it assigns out. A base class in the user's own files still counts, and a class from an installed library is read as before. Both configs of `ProcessModel` and `MPCModel` now list only the GEKKO variables (and `y`); the distillation Gym environment (a `gym.Env`) has the same outputs as before. Test: `test_a_library_base_class_state_is_not_an_output`.
- **An attribute set in `__init__` that the step leaves unchanged isn't an output.** The first version of the distillation class set its compositions in `__init__`; the probe's step at the same reflux ratio didn't change them, so `--probe` found no outputs. That's by design (the probe can only tell results from what changes), so the class sets them in `step()`.

## Problems found

1. **`--compile nuitka` fails on any model whose dependency tree has a single-file top-level module.** fmugen passes `--include-package-data=NAME` for every import name of every collected distribution ([distribute.py:177](../src/fmugen/distribute.py#L177)). Some of those are plain modules, not packages: matplotlib's `pylab.py`, jupyter's `jupyter.py`, `ipython_pygments_lexers.py`. Nuitka stops: `FATAL: Error, 'pylab' is a module not a package, cannot have package data.` This failed all 6 compiles (5 on `pylab`, OpenHENS on `jupyter`, needforheat on `ipython_pygments_lexers`). PyInstaller's `--collect-data` accepts modules, so the PyInstaller path isn't affected. Nuitka hadn't been run before ([rerun](tested-models-rerun.md): "Not checked: Nuitka"). The fix is to pass `--include-package-data` only for names whose spec has `submodule_search_locations`.
2. **A model file named `model.py` can't be built.** `fmugen build`: `model module 'model' clashes with a UniFMU backend module (abstract_backend, backend, fmugen_launch, fmugen_runtime, main, model, schemas); rename the file`. `init` writes the config without a warning. This is intended: renaming the file is an acceptable request.
3. **Results kept as GEKKO variables on the object aren't found.** `SimpleBioreactor.solve()` returns `None` and leaves its trajectories in `self.X` and `self.S`, GEKKO `GKVariable` objects whose `.value` is the solved array. Both configs say `no outputs found: add [outputs] by hand`. The FMU builds and simulates, but only the inputs show up. CGE's `results()` has the same shape (`self.pK`, `self.W['GOVR']`). This is GEKKO's usual pattern (`x.value` after `m.solve()`), so most class-based GEKKO models will hit it.
4. **An exception raised while importing a script model is shown as a raw traceback.** Importing `ethanol_bioreactor.py` runs its `m.solve()`, which fails. `init` prints the full traceback through `fmugen/interface.py` rather than a `fmugen: error: importing ethanol_bioreactor.py failed: …` line. The distillation script, which imports fine, gets a clean `fmugen: error: cannot tell which function or class is the model (found: none)`.
5. **With FMI 2, the backend's error isn't shown without debug logging, and debug logging can crash FMPy.** Without `debug_logging`, a failed step reports only `fmi2DoStep failed with status 3 (error)` (OpenHENS): the Python traceback isn't logged at error level. With `debug_logging=True`, Pyomo's DEBUG log lines reach FMPy, and FMPy crashes with `access violation reading 0x…2D8E` partway through them. That's UniFMU's [§12](unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings) (log messages used as printf format strings). OpenHENS's real error (`couenne solver not found`) was found by calling it directly.
6. **The backend outlives a failed FMU** (known: [fmpy-limitations.md §1](fmpy-limitations.md#1-simulate_fmu-doesnt-free-the-instance-after-an-fmu-error)). In the first attempt, the test harness read the simulation's output through a pipe, and the orphaned backend kept it open, so the NHES and drilling runs hung until stopped. The harness then wrote the output to a file and killed the backend after each simulation.

## Results

Columns as in [tested-models-rerun.md](tested-models-rerun.md#results): **init / init --probe**: config written. **build + simulate**: per config. **compile**: the config compiled with Nuitka, and the result. **First error**: the first failing step's error.

| Model | FMI | init | init --probe | build + simulate (per config) | compile (nuitka) + simulate | First error |
|---|---|---|---|---|---|---|
| `ethanol_bioreactor.py` (script) | 2 | ✗ | ✗ |  | — | Importing runs the script's own solve, which fails: GEKKO's local solver (APMonitor 1.0.3) stops with `Exception: Access Violation at line 8272 of file ./f90/ace.f90` after a number of successful sequential steps, then `FileNotFoundError: …options.json`. Same when the script is run directly with `python`: **not fmugen's**. With `remote=True` the APMonitor server wasn't reachable from this machine. fmugen shows it as a raw traceback (problem 4). |
| `distillation.py` (script) | 2 | ✗ | ✗ |  | — | `fmugen: error: cannot tell which function or class is the model (found: none); use distillation.py:Name`. The script runs fine on its own (two solves, then plots). |
| `DistColEnvDynInc_altrewards:DistColEnvDynInc` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / **probe ✓** | probe: ✗ | Code-only config: `TypeError: can only concatenate list (not "float") to list` (`Action` given as one Real; `--probe` makes it an array). Probe config: 36 variables. The state (`y0`, 9 integers), reward (`y1`: 0.0, 0.230, −0.329, −0.087), `done` and message change every step. Compile: problem 1 (`pylab`). |
| `Bioreactor:SimpleBioreactor` | 2 | ✓ | ✓ | plain ✓* / probe ✓* | probe: ✗ | *Builds and simulates, but with **no outputs**: the results are GEKKO variables in `self.X` / `self.S` (problem 3). Compile: problem 1 (`pylab`). |
| `transmembrane_lib:gekko_sim_method` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: ✗ | `NameError: name 'GEKKO' is not defined`: the library never imports GEKKO, and the class also uses an undefined `m` and `tstop`. Dead code upstream, **not fmugen's**. Without `--kind function`: `cannot tell which method of gekko_sim_method runs a step (public methods: none)`, which is correct. Compile: problem 1 (`pylab`). |
| `mpc:solveMPC` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: ✗ | `AttributeError: 'float' object has no attribute 'X'`: the constructor takes the Gym environment object (`env.X`, `env.Y`), and `init` made up `env = 0.0` (`env: no default in the code: the start value is made up, check it`). No outputs found either (`action` returns an int computed from `self.m`). It also solves with `remote=True`, which needs a network. Compile: problem 1 (`pylab`). |
| `simple_nhes:model` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: ✗ | `initialization failed: FileNotFoundError(2, 'No such file or directory')`: `model()` always reads `./grid_data/more_data_scaled.csv`, which isn't in the repository (`get_data.py` downloads only result files). Config: 25 inputs, 22 outputs. Compile: problem 1 (`pylab`). |
| `rhc_analysis:Model` (needforheat) | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: ✗ | `AttributeError: 'Model' object has no attribute 'index'`. `Model`'s methods are written without `self`, to be called as `Model.building(df_learn, …)`; fmugen builds a `Model()` and calls `instance.building(…)`, so the instance arrives as `df_learn`. Either way, `df_learn` is a pandas DataFrame of measurements, which no FMU input can give. It also needed CoolProp, which isn't in its `requirements.txt`. Compile: problem 1 (`ipython_pygments_lexers`). |
| `openhens:OpenHENS` | 2 | ✓ | ✓ | plain build ✓, sim ✗ / probe build ✓, sim ✗ | probe: ✗ | `Exception: couenne solver not found. Please check the solver is installed and the path is correct.` (found by calling it directly, problem 5): OpenHENS needs the COIN-OR binaries on PATH, as its README says; not installed here. Through FMPy: `fmi2DoStep failed with status 3 (error)`, or an access violation with debug logging on. Compile: problem 1 (`jupyter`). |
| `Code/model:CGE` | 2 | ✓ | ✓ | plain ✗ / probe ✗ | — | `fmugen: error: model module 'model' clashes with a UniFMU backend module …; rename the file` (problem 2). With pandas 3, the model itself fails (its chained `df[a][b] = …` assignments don't write under copy-on-write, so GEKKO gets `nan`); with pandas 2.3.3, used for this run, it runs directly (`HOU1 Wealth 117.843`). The `--probe` call works, but finds **no outputs**: `results()` prints its table and returns `None`, and the solution is in GEKKO variables (`self.pK`, `self.W[...]`), problem 3. |

Not checked: the probe and simulated values against a direct run of each model (only the distillation environment simulated with outputs), and a Nuitka build of any model past problem 1.
