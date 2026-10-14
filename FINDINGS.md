# fmugen: bugs, gaps and feature ideas

Date: 2026-10-14 · Branch `dev` @ `e3276ac`

This is a follow-up to [AUDIT.md](AUDIT.md) (2026-10-05/06). It lists what is **new** since that audit, and then which of the audit's items are **still open**. I read all of `src/fmugen` (CLI, config, XML writer, composite, distribute, runtime, adapters, launcher) and skimmed the inference code (`interface.py`, `static.py`) and the Docker demo.

- **[verified]** means I reproduced it on this machine (UniFMU 0.14.0, the project's uv env).
- **[code]** means I found it by reading the code and did not run it.

---

## 1. Bugs

### 1.1 ✅ Fixed: The GUID changes on every build, unlike what the code and the audit say [verified]
`stamp_guid` (`description.py`) hashes every file of the FMU, **including `modelDescription.xml`**. That file contains `generationDateAndTime`, which is "now" unless `SOURCE_DATE_EPOCH` is set. So two builds of an unchanged model get different GUIDs:

```
build examples/psychrometry -> guid {129a4177-…}  generationDateAndTime 12:27:17Z
build examples/psychrometry -> guid {d80b1a5f-…}  generationDateAndTime 12:27:21Z
```

The comment above `GUID_PLACEHOLDER` and AUDIT.md §5.5 both say "an unchanged model rebuilds to the same GUID". `test_builds_are_reproducible` sets `SOURCE_DATE_EPOCH`, so it doesn't catch this.
**Fix:** hash `modelDescription.xml` with `generationDateAndTime` blanked, or hash before writing the date. Then add a test that builds twice **without** `SOURCE_DATE_EPOCH` and compares the GUIDs.

### 1.2 ✅ Fixed: Tunable parameters bound by position are silently ignored after initialization [verified]
A class parameter with `variability = "tunable"` and `to = "pos:N"` becomes `initpos`. `_variable` (`config.py:733`) only sets `attr` for `init` and `attr` bindings, so this parameter has no `attr`. In step mode, `Engine.set_values` stores the new value and returns **OK**, but nothing reaches the object.

I checked this with `simple_pid:PID` and `Kp = { start = 2.0, variability = "tunable", to = "pos:0" }`. After `set_values(Kp, 100)` the status is 0 and `obj.Kp` is still `2.0`.

The same thing happens when `to = "init:x"` but the constructor stores the value under another name (`self._x = x`). `setattr(obj, "x", …)` then creates a new attribute that nothing reads, and nobody is told.
**Fix:** at build time, refuse `tunable` with an `initpos` binding unless `attr` is given. For `init:x` without `attr`, warn when the class has no attribute `x` (`static.assigned_attributes` already knows which attributes `__init__` sets).

### 1.3 🟠 FMI 2 log messages with `%` can crash the importer: still no workaround [code + documented]
This is documented in [unifmu-limitations.md §12](docs/unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings) but not fixed. Any traceback or URL in the log that contains `%s` causes an access violation in FMPy when logging is on. fmugen pins UniFMU 0.14.0 exactly, so the fix is safe and very small: in `model_fmi2.py`'s `log()`, send `message.replace("%", "%%")`. Remove it when the UniFMU pin moves to a fixed version. Of all the crash paths, this is the cheapest one to remove.

### 1.4 ✅ Fixed: Function models are called with `dt = 0` at initialization when there is no `[experiment] step_size` [code]
For function entries, `init_call` defaults to true. `exit_initialization_mode` then calls `self._call(self.time, self.experiment.get("step_size", 0.0))`. So:
- A function that divides by its `dt` / `step_size` argument raises `ZeroDivisionError` at initialization, and the FMU never starts.
- With `step_size` set, the init call uses the **experiment's** step size, which may not be the importer's.
- The function runs once more than the number of steps: once at init (at t0), then again in the first `doStep` (also at t0). That matters for functions with side effects or `[model] globals` counters.

**Suggestion:** skip the time arguments that would be 0 at init (or skip the init call) when a `step_size` source is bound, and document that function models are also called at initialization.

### 1.5 ✅ Fixed: Composite parts can share helper modules by accident [code]
`Composite.__init__` only rejects parts whose **entry files** have the same stem. If two parts each have their own `utils.py` or `helpers/` in `sources`, everything runs in one process, so the second part imports the first part's module from `sys.modules` and silently runs the wrong code. Packages entered as `pkg.module:Name` aren't checked at all.
**Fix:** compare the top-level names of every part's `sources` and `entry_import()` module, not only the entry stems.

### 1.6 ✅ Fixed: Composite connections don't check types [code]
`combine` checks causality and size but not type. `String → Real`, `Real 0.5 → Integer`, or an enumeration with different items all build fine, then fail (or get coerced in odd ways) on the first `doStep`. Check `type` (and `declared_type` items) at build time.

### 1.7 ✅ Fixed: Constants aren't reset with `fmi*Reset` or saved with the FMU state [code]
`_resolve_constants` caches `{ python = … }` and `{ call = … }` constants once per process. If the model mutates one in place (a list, a numpy array, a loaded object passed as a keyword), the change survives `reset()` and isn't restored by `deserialize`. So a rollback or reset doesn't give the same results. Either deep-copy the constants per call, or re-resolve `python` constants on reset and document that `call` constants are shared.

### 1.8 🟢 Smaller ones [code]
- **`fmi3GetIntervalFraction` / `GetShiftFraction`**: `fraction()` uses `Fraction(str(value))`, so an interval like `1e-20` gives a resolution above the uint64 maximum. Use `Fraction(value).limit_denominator(2**63)`.
- **`fmi3DoStep` returns `lastSuccessfulTime = t + h` even on error.** It should return `t` when the step failed.
- **The FMI 3 `Model.__init__` ignores `logging_on`** (and FMI 2 has no equivalent). The engine starts with `logging_on = True`. Starting from the importer's value would also cut the `[output]` and forwarding work when logging is off.
- **The `--capture-output` temp file grows forever** (`_capture_output`). It is read incrementally but never truncated. A long simulation that prints a lot fills the temp disk. Truncate it after each `_forward_output`.
- **The build deletes the previous output before zipping** (`output.unlink` and then `_write_zip`). If zipping fails (disk full, a file locked by an importer on Windows), the old FMU is lost. Write to `output.with_suffix(".tmp")` and `os.replace` it.
- **`hf_models` treats any `a/b` string start value as a Hugging Face repo id** when the path doesn't exist relative to `base_dir`. With `--vendor`, a string parameter like `"data/input.csv"` (relative to `cwd`, not the config) or `"W/m2"` makes a network call to the Hub (caught, so only a misleading note).
- **Three lines lost their line break** in an earlier edit and now have long runs of spaces inside an expression: `__main__.py:228`, `interface.py:180` and `interface.py:342`. They are valid Python but hard to read. Reformat them.

---

## 2. Gaps (portability and robustness)

### 2.1 🟠 Orphan backends: fmugen could work around UniFMU §2
[unifmu-limitations.md §2](docs/unifmu-limitations.md#2-the-backend-keeps-running-after-an-fmu-error) shows that the backend waits forever once the importer is gone, because nothing watches the parent process. fmugen's runtime is inside that process, so it can fix this without UniFMU's help: when `Engine` starts, start a daemon thread that checks every few seconds whether the parent process is alive (`os.getppid()` changing to 1 on POSIX; `OpenProcess`/`WaitForSingleObject` via `ctypes` on Windows) and calls `os._exit` if it isn't.

Two extra process layers make this worse today:
- `fmugen_launch.py` (`--vendor`) uses `subprocess.call` for `main.py`.
- `compiled_launch_command` uses `powershell -command …` on Windows (and `sh -c` elsewhere).

On Windows, killing the outer process leaves the inner one running. Use `os.execv` on POSIX in the launcher. On Windows, a Job object or the watchdog above handles it. Calling the `.exe` directly instead of through PowerShell also saves PowerShell's ~0.5–1 s startup per instance.

### 2.2 🟡 `--vendor` on Windows runs `python`, which may be the Microsoft Store stub
`launch.toml` for vendored FMUs uses `python` on Windows and `python3` elsewhere. On a clean Windows machine, `python` is often the App Execution Alias that opens the Store. Prefer the `py -3` launcher when it exists (or let `fmugen_launch` be started through `py`), and let users override the interpreter at runtime, e.g. with `FMUGEN_PYTHON`.

### 2.3 🟡 Model files that shadow the standard library are still accepted (AUDIT §3.2, open)
`RESERVED_MODULES` (`config.py:38`) still doesn't check `sys.stdlib_module_names`. A model file called `logging.py`, `json.py`, `random.py` or `queue.py` breaks the backend itself. This is a one-line check in `entry_import()` (and in `_local_sources` for the other files).

### 2.4 🟡 `interface.json` `spec_version` is never checked (AUDIT §5.2, open)
`Engine` doesn't read it. Since `fmugen_runtime.py` is copied into each FMU, this only matters for composite parts or tools that read `interface.json`. Still, a one-line check costs nothing.

### 2.5 🟡 Python floor (AUDIT §2.4, open)
`requires-python = ">=3.13"`. The build side really needs **3.11** (`tomllib`, `datetime.UTC`, `contextlib.chdir`, `hashlib.file_digest`), and the runtime inside the FMU needs **3.10** (`types.UnionType`, `match` in UniFMU's backend). Lowering to 3.11 is now a metadata change plus CI.

### 2.6 🟢 Model behaviours with no support yet
- **Discard (variable-step masters).** A model can't reject a step (`Status.discard` is unused). Proposal: map a specific exception (e.g. `fmugen.Discard`, or a configurable exception class like `[model] discard_on = ["scipy.integrate:IntegrationWarning"]`) to `discard`, with the step rolled back. Rollback is cheap because the engine already serialises its state.
- **`[time]` sources:** `start_time`, `stop_time` and `tolerance` are stored but can't be passed (AUDIT §5.4, open). It is a three-line addition to `TIME_SOURCES` and `Engine._call`, and very useful for `solve_ivp(rtol=tolerance)` models.
- **Generators and `async def` models** (AUDIT §4, open).
- **`--compile` for composites**, and clocks or structural parameters inside composites (AUDIT §4, open).

---

## 3. New features

Ordered by value for users, with the main files each one touches.

| # | Feature | Why | Where |
|---|---|---|---|
| 1 | **`fmugen check MODEL`**: validate the config, import the model, print a table of variables (name, causality, type, binding, start, unit); `--run N` does N steps in-process with `Engine` (no UniFMU) | Fastest feedback loop. The runtime already works in-process (I used it like this for 1.2) | new subcommand, `Engine` |
| 2 | **`fmugen run FMU --stop-time … [--input csv] [--plot]`**: a thin FMPy wrapper that also turns on FMI logging, with `loggingOn=True`, so errors are visible (UniFMU §3 drops them when logging is off) | Users hit "failed with status 3" without a reason | new subcommand |
| 3 | **`fmugen inspect FMU`**: shows interface.json, the fmugen/UniFMU versions, the mode (venv / vendor / compile / distributed), platforms and requirements | Debugging FMUs received from others | new subcommand; also write `fmugen_version` into interface.json |
| 4 | **Record the fmugen version** in `interface.json` and in `generationTool` (`fmugen 0.1.0 + unifmu 0.14.0`) | Today, nothing in an FMU says which fmugen built it | `normalize`, `description.py` |
| 5 | **Process watchdog** (2.1) | Removes the most annoying failure mode on Windows | runtime |
| 6 | **Discard support** (2.6) | Variable-step and error-controlled masters | runtime, config |
| 7 | **`FMUGEN_DEBUG=1` / `--debug`**: in the FMU, also write the log and the tracebacks to a file in the temp dir | Gets errors out even when the importer drops them (UniFMU §3, §13) | runtime |
| 8 | **Units from annotations and docstrings** (`Annotated[float, "K"]`, numpydoc `Parameters`), and `BaseUnit` in `UnitDefinitions` for SI units | Fewer manual edits after `init`; importers can check units | `static.py`, `description.py` |
| 9 | **JSON Schema for `fmugen.toml`** | Editor completion through Taplo / Even Better TOML | new file, from `VAR_KEYS`/`MODEL_KEYS` |
| 10 | **Public Python API** (`fmugen.build(...)`, `fmugen.init(...)`) with documented signatures; `build` already returns `(path, interface)` | Notebooks and CI scripts | `__init__.py` |
| 11 | **Min/max checks at build time** (`min <= start <= max`, `min <= max`), and at runtime for inputs (FMI says out-of-range values may be refused) | FMPy's `validate` complains later, with less context | `config._variable`, `Engine.set_values` |
| 12 | **Multi-OS compiled FMUs**: merge `dist/` folders built on several OSes into one `.fmu` (`fmugen merge a.fmu b.fmu -o all.fmu`) | `--compile` is single-OS today (AUDIT §3.1) | new subcommand; `launch.toml` already has one entry per OS |
| 13 | **Configurable proxy port / reconnect** for `--distributed`, once UniFMU allows it; until then a small helper that tails the proxy's log for the port and starts the private side (`fmugen serve`) | Today a human has to copy the port by hand on every run (UniFMU §14) | private side |
| 14 | **Opt-in `pytest -m pypi` suite** built from `docker/models/r3/*/fmugen.toml` (already 46 configs in the repo) | Keeps the promise that it "works on real published models" checked automatically | `tests/` |

---

## 4. Tests, CI and repo hygiene

- **No CI yet** (`.github/` doesn't exist). Start with a Windows + Linux job: `uv sync`, install UniFMU 0.14.0 from the release, then `pytest -m "not slow"`. Add the slow `--compile` tests nightly.
- **The quick suite is slow:** `pytest -m "not slow"` gives 156 passed, 9 skipped in **11 min** on this machine. Most of that is UniFMU subprocess runs. Mark those `slow` (or add an `fmu` marker), so the in-process `Engine` tests make a sub-minute loop.
- **Missing tests**, each of which would have caught a bug above:
  - GUID stability without `SOURCE_DATE_EPOCH` (1.1).
  - A tunable parameter changed in step mode, for each binding kind (`init`, `initpos`, `attr`, `call`, `arg`) (1.2).
  - An FMI 2 log message containing `%s` (1.3).
  - A function model with a `dt` argument and no experiment step size (1.4).
  - A composite whose two parts each have a `utils.py` (1.5).
- **No `LICENSE`** (AUDIT §2.5, still 🔴). This blocks any public release, and the licence of the generated FMUs (which contain fmugen's runtime and UniFMU's MIT code) needs a sentence in the docs.
- **AUDIT.md is partly stale.** §7 says the Docker demo is FMI 2 only, but `docker/app/fmu_runner.py` now handles `FMU3Slave` too. §3.1 says `--python` and `--vendor` were removed, but `--vendor` exists. Mark it as a historical document, or update the status column.
- `image.png` at the root, and `.gitignore` entries for `out/`, `dist/` and `.pytest_cache/` (AUDIT §7, open). `out/` is untracked but sits in the root.
- `src/fmugen/__init__.py`: still no `__version__` (AUDIT §7, open).

---

## 5. Still open from AUDIT.md (short list)

| Audit item | Status today |
|---|---|
| §2.5 LICENSE / third-party notices | open |
| §2.4 `requires-python >= 3.13` | open (see 2.5) |
| §3.2 stdlib shadowing | open (see 2.3) |
| §5.1 `--debug` flag | open |
| §5.2 `spec_version`, FMI 2 `Int64` widening, docstring truncation, JSON Schema | open |
| §5.3 `_local_sources` picking up `.venv`/`build`/`dist`; `_pick_entry` ignoring re-exports; more state-name conventions | open |
| §5.4 `start/stop_time` + `tolerance` as time sources; honouring debug-logging categories; `Status.discard`; `reset()` not calling `terminate` | open |
| §5.5 `BaseUnit`, `displayUnit`, `<Annotations>` | open |
| §5.7 report the 4 KB hang upstream; `init --probe` suggesting `--capture-output` | open |
| §6 CI, wheel-install test, other importers (fmusim / OMSimulator), Hypothesis tests, ruff / pyright | open |
| §8 Tier 4 developer-experience commands | open (see §3 above) |
