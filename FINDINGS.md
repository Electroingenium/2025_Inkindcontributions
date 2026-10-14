# fmugen review: open items, fixed items and feature ideas

This file combines two reviews of the whole repository:

| Review | Branch | Scope |
|---|---|---|
| 2026-10-05, status updated 2026-10-06 | `tomas` @ `30d827b` … `8aa4903` | All first-party source, the UniFMU integration, tests, docs, examples, the Docker demo, packaging and repo hygiene, with a focus on **portability, installability and how wide a range of models fmugen handles**. Checked by reading the code, running the tests, building the wheel and probing model shapes with `fmugen init`. |
| 2026-10-14 | `dev` @ `e3276ac` … | All of `src/fmugen` again (CLI, config, XML writer, composite, distribute, runtime, adapters, launcher), the inference code (`interface.py`, `static.py`) and the Docker demo, looking for bugs, gaps and features. Most of what it found is fixed (§4). |

- **[verified]** means the finding was reproduced (UniFMU 0.14.0, the project's uv environment, Windows).
- **[code]** means it was found by reading the code.

---

## 1. Summary

The core design is sound. The user's code is never touched: a sidecar `fmugen.toml` holds the mapping, one runtime engine sits behind thin FMI 2 and FMI 3 adapters, and the error messages say what to do. The documentation is thorough, and the tests run real FMUs through UniFMU for both FMI versions.

What still stands between fmugen and an open-source release is **distribution**, not the core logic:

| Severity | Item | Section |
|---|---|---|
| 🔴 | No `LICENSE` file, and no statement of the licence of generated FMUs | [2.1](#21-before-a-public-release) |
| 🟠 | No CI, and no test that installs the built wheel | [2.1](#21-before-a-public-release), [2.6](#26-tests-and-quality) |
| 🟠 | A backend whose importer has gone keeps running forever (UniFMU), made worse by fmugen's launcher layers | [2.2](#22-portability) |
| 🟠 | UniFMU 0.14 hangs when the model prints more than ~4 KB; fmugen's workaround (`--capture-output`) is opt-in | [2.3](#23-unifmu-problems) |
| 🟡 | `--vendor` FMUs start `python` on Windows, which may be the Microsoft Store stub | [2.2](#22-portability) |
| 🟢 | Model coverage gaps: discard, more time sources, generators/async, composites with `--compile` or clocks, Model Exchange | [2.4](#24-model-coverage) |

---

## 2. Open items

### 2.1 Before a public release
- **🔴 No `LICENSE`.** Without one the code is "all rights reserved" and can't legally be reused.
  - Every generated FMU contains UniFMU's binaries and backend (MIT, INTO-CPS Association). The docs should say so, so that people who ship FMUs include UniFMU's licence.
  - Generated FMUs also contain fmugen's runtime. State the licence that applies to them (a permissive licence, or an explicit exception), so FMUs can be shipped commercially.
  - Example code (simple-pid, RC_BuildingSimulator, FilterPy) is credited in the README and `rc_simulator/LICENSE` is present; check that each vendored example carries its licence file.
- **Package metadata:** no `license` field (no licence yet), no project URLs (no public repository yet), and a static version (consider `hatch-vcs` and a `CHANGELOG.md`). Check that the name `fmugen` is free on PyPI before the first upload; until then fmugen is installed from a checkout or a built wheel. Once on PyPI, the README can add `pipx install fmugen` / `uv tool install fmugen`.
- **CI:** see [2.6](#26-tests-and-quality).

### 2.2 Portability
- **🟠 Orphan backends.** [unifmu-limitations.md §2](docs/unifmu-limitations.md#2-the-backend-keeps-running-after-an-fmu-error): when the importer exits without freeing the instance (an error path, a crash, a kill), UniFMU's backend waits forever, because nothing watches its parent process. fmugen's runtime runs inside that process, so fmugen can fix it on its own. When `Engine` starts, it can start a daemon thread that checks every few seconds whether the parent is alive (`os.getppid()` changing on POSIX; `OpenProcess`/`WaitForSingleObject` through `ctypes` on Windows) and calls `os._exit` if it isn't. [verified: three orphaned backend pairs were left by hung test runs on 2026-10-14]
  Two of fmugen's own process layers make this worse. `fmugen_launch.py` (`--vendor`) runs `main.py` with `subprocess.call`, and `compiled_launch_command` goes through `powershell -command …` on Windows (`sh -c` elsewhere). On Windows, killing the outer process leaves the inner one running. Use `os.execv` in the launcher on POSIX, and a Job object or the watchdog on Windows. Starting the `.exe` directly instead of through PowerShell would also save PowerShell's ~0.5–1 s startup per instance.
- **🟡 `--vendor` on Windows runs `python`** (`python3` elsewhere). On a clean Windows machine `python` is often the App Execution Alias that opens the Microsoft Store. Prefer the `py -3` launcher when it exists, and let users choose the interpreter at runtime (e.g. `FMUGEN_PYTHON`). [code]
- **Multi-OS compiled FMUs.** `--compile` freezes for the OS it runs on. Shipping one FMU for several OSes needs one build per OS plus a step that merges their `resources/dist/` folders (`launch.toml` already has one entry per OS).
- **`--embed-python`** (opt-in): a python-build-standalone interpreter inside the FMU, for fully offline FMUs that keep their sources (unlike `--compile`).
- **The exact `protobuf==5.27.3` pin** comes from UniFMU's generated `*_pb2.py` files and lands in the user's environment, where it can conflict with packages that pin protobuf too (TensorFlow, grpcio, …). Regenerating the schemas, or testing a range like `protobuf>=5.27,<6`, would loosen it.
- **Python floor.** `requires-python = ">=3.13"`. The build side needs 3.11 (`tomllib`, `datetime.UTC`, `contextlib.chdir`, `hashlib.file_digest`) and the runtime inside the FMU 3.10 (`types.UnionType`; `match` in UniFMU's backend). **Decision (2026-10-14): it stays at 3.13.**

### 2.3 UniFMU problems
The full list is in [docs/unifmu-limitations.md](docs/unifmu-limitations.md). Still to act on:
- **🟠 The ~4 KB console hang** ([§1](docs/unifmu-limitations.md#1-the-importer-hangs-when-the-model-prints-more-than-4-kb)): when the FMU's Python writes more than about 4 KB to stdout/stderr, UniFMU's native library panics (`zeromq-0.4.1/src/rep.rs:168:40: not yet implemented`) and the importer waits forever. [verified] fmugen's workaround, `build --capture-output`, is off by default, so a model that prints a lot hangs unless built with it. Library log records count too, because UniFMU's backend echoes them to its console: a model that logs one line per step hangs after about 100 steps. [verified 2026-10-14]
  - Report it upstream, with the small reproduction (a function that prints 5 KB).
  - Have `init --probe` suggest the flag when its probe call prints a lot, or consider turning capture on by default.
- **Report upstream:** FMI 2 log messages used as printf format strings ([§12](docs/unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings); fmugen works around it, see §4) and the backend exit that aborts the importer ([§13](docs/unifmu-limitations.md#13-a-backend-that-exits-during-a-call-can-abort-the-importer)).

### 2.4 Model coverage
Already supported, each checked with published models ([docs/tested-models.md](docs/tested-models.md) and its later rounds): functions and classes; attributes, properties and setter methods; positional-only arguments of C extensions; `setup` calls; `kind = "function"`; arrays and numpy (FMI 3 arrays, FMI 2 one scalar per element); enums; clocks; factories (`[model] create`, a function entry with `call`); computed constants (`{ call = … }`); converted inputs (`convert = "torch:tensor"`, `"pint"`); tuple, dict and dataclass/pydantic/attrs arguments; NamedTuple, nested dict/object, pandas and xarray results; anything with `__float__`; module globals; data files with `[model] cwd`; composite FMUs; Hugging Face weights bundled with `--hf-weights`.

Still missing:
- **Discard.** A model can't reject a step: `Status.discard` is never returned, but variable-step masters rely on it. Map a specific exception (`fmugen.Discard`, or a configurable class like `[model] discard_on = ["scipy.integrate:IntegrationWarning"]`) to `discard`, with the step rolled back. Rollback is cheap, since the engine already serialises its state.
- **More `[time]` sources.** `start_time`, `stop_time` and `tolerance` are stored but can't be passed to the model. Adding them to `TIME_SOURCES` and `Engine._call` would let ODE models use `solve_ivp(rtol=tolerance)`.
- **Generators and coroutines** (`yield`-based models, `async def step`): drive them with `next()`/`send()`, or `asyncio.run` per step. Left open because no published generator or async model was found to test against; simpy models already work through a factory calling `env.run(until=…)`.
- **Composites:** `--compile` of a composite FMU, and parts with clocks, structural parameters or `[events]`.
- **Model Exchange (FMI 2 and 3)** for ODE models (`[model] kind = "ode"` with `derivatives = "return"` and continuous states), so the importer's own solver integrates them. UniFMU's Python backend has no Model Exchange, so this needs an upstream contribution or another native wrapper. It's the FMI capability users will ask for most.
- **An internal solver helper** (`[model] integrate = "rk4" | "scipy:RK45"`) that turns an ODE right-hand side `f(t, x, u)` into a co-simulation FMU, with internal sub-steps and the tolerance passed in. It covers ODE models without Model Exchange.
- **Other model formats:** Jupyter notebooks (`.ipynb` entry), scikit-learn (`kind = "sklearn"` calling `predict` with the inputs as features) and standalone ONNX files. Six published PyTorch and ONNX Runtime networks already work unmodified.
- **Inference:** `x_prev` is the only state convention `init` recognises (also `x_old`, `last_x`, a `state` dict passed in and returned). `_pick_entry` only considers objects defined in the module, so a file that only re-exports (`from .core import Model`) gives "found: none"; fall back to `__all__`. `_local_sources` can pick up a `.venv`, `venv`, `env`, `build` or `dist` folder inside the config folder. `--probe` has no timeout for slow models.

### 2.5 Smaller code items
- **CLI:** `main()` only catches `FileExistsError` and `InterfaceError`, so an exception from user code during `build` prints a raw traceback. A `--debug` flag would let the default show a short message.
- **Config:** FMI 2 configs using `Float32`/`Int64` give a clear error; widening them (`Int64` becomes Integer with a range warning) would let one config build both versions. `description` comes from the first docstring line, unshortened. `start = 1` for a `Boolean` is rejected, correctly, but the error could suggest `true`. `min`/`max` aren't checked against `start` or each other at build time.
- **Runtime:** `do_step` doesn't warn when `current_time` doesn't match the FMU's time outside a rollback. `fmi2SetDebugLogging` / `fmi3SetDebugLogging` ignore `categories`. `reset()` drops the model object without calling its `terminate` method, so resources it holds (serial ports, files) wait for garbage collection. `deserialize` unpickles bytes from the importer: normal for FMUs, but the docs should say FMU state must come from a trusted source.
- **modelDescription:** `UnitDefinitions` only declare unit names; `BaseUnit` (SI exponents) for common units would let importers check and convert units. `displayUnit`, `relativeQuantity`, `unbounded`, `reinit` and `<Annotations>` aren't exposed (an escape hatch for extra attributes per variable would cover them). FMI 3 terminals and icons aren't supported (low priority).

### 2.6 Tests and quality
- **No CI** (`.github/` doesn't exist). Start with Windows and Linux (macOS later): `uv sync`, install UniFMU 0.14.0 from its release, then `pytest -m "not slow"`. Run the `slow` `--compile` tests nightly.
- **No test from an installed wheel.** That is how the first review found a wheel that couldn't build anything (§4).
- **FMPy is the only importer used.** Add [fmusim from the Reference FMUs](https://github.com/modelica/Reference-FMUs) and, optionally, OMSimulator: importers call functions in different orders.
- **The published-model tests are manual.** An opt-in `pytest -m pypi` suite built from the 46 configs in `docker/models/r3/*/fmugen.toml` would keep the promise that fmugen works on real published models checked.
- **Property-based tests** (Hypothesis) for `render_toml` → `load_config` round trips and for `coerce` / `reshape` / `flatten`.
- **No linter, formatter or type checker.** Add `ruff` (lint and format) and `pre-commit`. `pyright` or `mypy` in basic mode, plus a `TypedDict` for the interface spec, would catch dict-shape mistakes and document the spec.

### 2.7 Repository and docs
- **`.git` is about 75 MB.** Most of it is early commits shared with `main`: seven generated `.fmu`/`.zip` files (~26 MB) and a 71 MB `FMUs/ORIGINAL.fmu/binaries/linux64/unifmu.so`. Removing them means rewriting `main` too, or publishing from a fresh history.
- **Community files** for open source: `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and PR templates, `CHANGELOG.md`, `CITATION.cff` (the README already cites a paper).
- **`.gitignore`:** add `dist/`, `build/` and `*.egg-info`.
- **`image.png`** at the root is used by `docs/packaging.md`; it would sit better in `docs/img/`.
- **Docs site:** the docs are spread over many pages plus a long manual; MkDocs Material on GitHub Pages would add navigation and search.
- **Docker demo:** `docker-compose.yml` mounts `/var/run/docker.sock` into the Streamlit container, which gives that container root-equivalent access to the host, and publishes port 8501. `docker/Readme.md` should say so and recommend not exposing the port publicly. The demo doesn't use `--distributed` yet.

---

## 3. Feature ideas

Ordered by value for users.

| # | Feature | Why | Where |
|---|---|---|---|
| 1 | **`fmugen check MODEL`**: validate the config, import the model, print a table of the variables (name, causality, type, binding, start, unit); `--run N` runs N steps in-process with `Engine`, without UniFMU | The fastest feedback loop; the runtime already works in-process | new subcommand |
| 2 | **`fmugen run FMU --stop-time … [--input csv] [--plot]`**: a thin FMPy wrapper with FMI logging on, so errors are visible (UniFMU drops them when logging is off, [§3](docs/unifmu-limitations.md#3-error-messages-are-lost-when-logging-is-off)) | Users get "failed with status 3" without a reason | new subcommand |
| 3 | **`fmugen inspect FMU`**: interface.json, the fmugen and UniFMU versions, the mode (venv / vendor / compile / distributed), platforms and requirements | Debugging FMUs received from others | new subcommand |
| 4 | **Record the fmugen version** (`fmugen.__version__`) in `interface.json` and in `generationTool` (`fmugen 0.1.0 + unifmu 0.14.0`) | Nothing in an FMU says which fmugen built it | `normalize`, `description.py` |
| 5 | **Process watchdog** ([2.2](#22-portability)) | Removes the most annoying failure on Windows | runtime |
| 6 | **Discard support** ([2.4](#24-model-coverage)) | Variable-step and error-controlled masters | runtime, config |
| 7 | **`FMUGEN_DEBUG=1`**: inside the FMU, also write the log and tracebacks to a file in the temp folder | Gets errors out when the importer drops them (UniFMU §3, §13) | runtime |
| 8 | **Units from annotations and docstrings** (`Annotated[float, "K"]`, pint annotations, numpydoc `Parameters`), and `BaseUnit` for SI units | Fewer edits after `init`; importers can check units | `static.py`, `description.py` |
| 9 | **JSON Schema for `fmugen.toml`** | Completion and validation in editors (Taplo / Even Better TOML) | new file, from `VAR_KEYS` / `MODEL_KEYS` |
| 10 | **A documented Python API** (`fmugen.build(...)`, `fmugen.init(...)`); `build` already returns `(path, interface)` | Notebooks, CI scripts, other tools | `__init__.py` |
| 11 | **`init --interactive`**: ask about the ambiguous choices (which method, units, which attributes are outputs) instead of making the user edit TOML | Easier first config | `__main__.py` |
| 12 | **Merge compiled FMUs from several OSes** (`fmugen merge a.fmu b.fmu -o all.fmu`) ([2.2](#22-portability)) | `--compile` is single-OS | new subcommand |
| 13 | **A helper for `--distributed`** that reads the proxy's port from its log and starts the private side (`fmugen serve`), until UniFMU lets the port be set ([§14](docs/unifmu-limitations.md#14-the-distributed-proxys-port-cant-be-set)) | Today the port is copied by hand on every run | private side |
| 14 | **Watch mode** (`fmugen build --watch`) | A fast edit → build → simulate loop | `__main__.py` |
| 15 | **Plugin hooks** (entry points, `fmugen.converters`) for custom result and input types | Third parties can add types without changing fmugen | runtime, inference |
| 16 | **`pytest -m pypi` suite** ([2.6](#26-tests-and-quality)) | Keeps the "works on real models" promise checked | `tests/` |

---

## 4. Fixed

### Review of 2026-10-05/06
| Item | What was done |
|---|---|
| The wheel had no UniFMU boilerplate, so `pip install` gave a tool that couldn't build anything [verified] | `fmugen build` runs `unifmu generate` and requires UniFMU 0.14.0 (on `PATH` or `FMUGEN_UNIFMU`; other versions are refused) |
| Placeholder package metadata, and dependencies fmugen never imported (PySide6, plotly, FMPy, …) | The package is `fmugen`, with real metadata; its dependencies are what UniFMU's backend imports (`protobuf==5.27.3`, `pyzmq`) plus `cloudpickle` |
| Which Python ran the FMU was unclear | The FMU runs with the environment fmugen is installed in (the model's). `--vendor` (wheels installed offline on first run; needs Python) and `--compile pyinstaller\|nuitka` (no Python, no sources, one OS) make FMUs for other machines. `--distributed` runs the model on another host |
| `build` and `init` ran the model, which is unsafe for hardware or network models | Neither does by default: `init` reads the source code, and only calls the model with `--probe` |
| Inference gaps: NamedTuple returns, nested dicts and objects, factories and tensors, number-like values (0-d arrays, `Decimal`, pint), lists in FMI 2, pandas/xarray results, dataclass/pydantic/attrs arguments, `Optional` annotations, composite models, data files, int outputs, `Boolean` strings, very large arrays (O(n²)), module globals, models that can't be pickled | All closed, each checked with a published model where one was found (see §2.4 for what's supported) |
| `init` crashed after importing `transformers` | Import cleanup reads `__dict__`, which doesn't trigger lazy imports |
| Printing more than ~4 KB hangs the importer (UniFMU) | `build --capture-output` sends the output to the importer's log (still opt-in, §2.3) |
| Builds weren't reproducible | The GUID is a hash of the FMU's files, `generationDateAndTime` follows `SOURCE_DATE_EPOCH`, and zip entries have fixed order, dates and modes |
| `.idea/` was tracked; `tools/unifmu.exe` (23 MB) was in the history of `tomas` | Untracked; removed from `tomas` with `git filter-branch` |

### Review of 2026-10-14
| Item | What was done |
|---|---|
| **The GUID changed on every build** [verified]: the hash included `modelDescription.xml`, whose `generationDateAndTime` is the build time unless `SOURCE_DATE_EPOCH` is set | The hash leaves the date out; a test builds twice without `SOURCE_DATE_EPOCH` |
| **Tunable parameters passed by position were silently ignored** after initialization [verified with simple_pid] | Refused without `attr`; tuning an attribute the object doesn't have is an error status. A test changes a tunable parameter between steps for every binding kind (`init`, `initpos`, `attr`, `call`, `arg`) |
| **FMI 2 log messages with `%` crashed the importer** (UniFMU passes them as printf format strings) [verified: access violation in FMPy] | Workaround: the FMI 2 adapter doubles each `%`, tested in-process and through UniFMU. Remove it when UniFMU fixes its logger ([§12](docs/unifmu-limitations.md#12-fmi-2-log-messages-are-used-as-printf-format-strings)) |
| **Function models were called with `dt = 0` at initialization** when `[experiment]` had no `step_size` | No init call in that case (`init_call = true` still forces it); the extra init call of function models is documented |
| **Composite parts could share helper modules** (two `utils.py` run as one) | Refused: every part's local modules are compared |
| **Composite connections didn't check types** | Checked at build time (integers and Booleans may feed floats, integers feed integers, enumerations need the same items) |
| **Constants changed in place weren't reset or restored** | Value constants are copied, saved with the FMU state and put back on reset; `{ call = … }` constants stay shared (documented) |
| Smaller: FMI 3 interval/shift fractions could overflow uint64; `fmi3DoStep` reported `t + h` as the last successful time after a failed step; FMI 3 ignored the importer's `logging_on`; the `--capture-output` file grew for the whole run; a failed build deleted the previous output; relative file paths were taken for Hugging Face repo ids; three lines had lost their line breaks | All fixed, with tests |
| **Model files named like a standard library module** (`json.py`, `queue.py`) broke the backend | Refused by `init` and `build` |
| **`spec_version` in `interface.json` was never checked** | The runtime refuses another version, also for each part of a composite |
| **The quick test suite took 5.5–11 min** | Builds generate UniFMU's template once per process and hard-link its binaries (a new copy of `unifmu.dll` took ~0.55 s to open while the virus scanner checked it): a folder build takes 0.34 s instead of 1.9 s. `packages_distributions()` (0.8 s per `init`) is cached. Tests that run FMUs through UniFMU are marked `fmu`: `pytest -m "not slow and not fmu"` takes about a minute, `-m "not slow"` about 2 min |
| No `fmugen.__version__`; the package docstring said FMI 2 only | Added, from the installed package's metadata; the docstring says FMI 2.0 or 3.0 |
| Docker demo was FMI 2 only, on Python 3.11 | It handles FMI 3 too, and its image is on Python 3.13 |

---

## 5. What is already good (keep it)

- **The user's code is never changed.** Every adaptation (positional-only arguments, setters, `kind = "function"`, setup calls, converters) is done in the config.
- **One engine and two thin adapters,** so FMI 2 and FMI 3 behaviour can't drift apart.
- **Errors say what to do,** e.g. "pass --call METHOD", "use model.py:Name", "arrays need --fmi 3".
- **`init` reads the code without running it,** and `--probe` finds what reading can't (array sizes, pickling); `build` checks the config against the imported code without running it.
- **`isolated_imports()`** keeps repeated builds and tests independent.
- **Generated configs are commented** and explain each guess.
- **The documentation** covers FMI behaviour function by function, packaging internals, UniFMU's and FMPy's limitations, and logs of the published models tried.
- **The tests run real FMUs through UniFMU,** not only mocks.
