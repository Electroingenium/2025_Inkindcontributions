# fmugen project audit

Date: 2026-10-05 · Branch `tomas` @ `30d827b` · Auditor: Claude (Opus 5.5)

Scope: the whole repository: `src/fmugen` (CLI, config, inference, XML writer, runtime templates), the UniFMU integration, tests, docs, examples, the Docker demo, packaging and repo hygiene. The project is meant to be open source, so the audit focuses on **portability, installability, and how wide a range of models it can handle**.

How it was checked:
- Read all first-party source.
- Ran the test suite: `uv run pytest` gives **38 passed in 120 s**.
- Built the wheel and listed what it contains.
- Probed a few model shapes with `fmugen init`.

Findings marked **[verified]** were reproduced. The rest come from reading the code.

---

## 1. Executive summary

The core design is sound and well made. The user's code is never touched, a sidecar `fmugen.toml` holds the mapping, one shared runtime engine sits behind thin FMI 2 and FMI 3 adapters, the probe runs at build time, and the error messages are clear. The documentation is unusually thorough, and the tests exercise real UniFMU runs for both FMI versions.

The main risks for an open-source release are **distribution and portability**, not the core logic:

| # | Severity | Issue |
|---|---|---|
| 1 | ✅ Fixed | The wheel did not contain the UniFMU boilerplate. fmugen now runs `unifmu generate` and requires UniFMU 0.14.0 to be installed |
| 2 | 🔴 Critical | **No LICENSE file** |
| 3 | ✅ Fixed | The FMU's Python was unclear. By default the FMU runs with the model's venv; `--vendor` (offline wheels, needs Python) and `--compile pyinstaller/nuitka` (no Python, no sources, one OS) make FMUs for other machines |
| 4 | ✅ Fixed | Placeholder package metadata and bloated dependencies. The package is now `fmugen`, depending only on what the FMU's backend needs |
| 5 | 🟡 Medium | `requires-python >= 3.13` excludes many users. The code needs about 3.11 (`tomllib`) and the FMU runtime needs 3.10 (`match` in the backend) |
| 6 | ✅ Fixed | The model was always run to build and to infer the config, which was unsafe for hardware or network models (e.g. tclab). Now neither `fmugen build` nor `fmugen init` runs it: `init` reads the source code, and only calls the model with `--probe` |
| 7 | 🟡 Medium | Some inference gaps reduce the "works on any model" coverage (see §4) |
| 8 | 🟢 Partly fixed | `.idea/` is no longer tracked, and `tools/unifmu.exe` is removed from the `tomas` branch history (not pushed yet). The pack is still large because of old generated `.fmu`/`.zip` files and a 71 MB `unifmu.so` in early commits on `main` |
| 9 | 🟢 Low | Builds are not reproducible (random GUID and current timestamp), there is no CI, and a few docstrings are stale |
| 10 | 🟠 High | **UniFMU 0.14 crashes when the FMU's Python prints more than about 4 KB**, and the importer hangs forever. Worked around with `build --capture-output` (§5.7); still needs an upstream fix |

---

## 2. Packaging and distribution

### 2.1 ✅ The wheel was missing the FMU boilerplate (fixed)
The wheel only contained `src/fmugen`, while the build copied the UniFMU boilerplate from `src/fmu`, outside the package. `pip install fmugen` therefore gave a tool that could not build anything [verified].

**Fixed:** `src/fmu` and `tools/unifmu.exe` were removed. `fmugen build` now runs `unifmu generate python <tmp> fmi2|fmi3` and requires the user to have **UniFMU 0.14.0** installed, either on `PATH` or through `FMUGEN_UNIFMU`. The version is checked with `unifmu --version`, and any other version is refused (`UNIFMU_VERSION` in `__main__.py`). The output of `unifmu generate` matched the removed folders byte for byte, apart from line endings.

Still to do: a CI job that installs the built wheel and UniFMU into a clean environment and builds an example FMU.

### 2.2 ✅ Project metadata (fixed)
The distribution was called `2025-inkindcontributions`, with the uv placeholder description and no authors, keywords or classifiers.

**Fixed:** the package is `fmugen`, with a real description, author, keywords and classifiers. A built wheel installed into a fresh model venv builds an FMU that FMPy simulates [verified].

Still open:
- No `license` field, because there is no licence yet (§2.5).
- No project URLs, because there is no public repository yet.
- The version is static. Consider `hatch-vcs` and a `CHANGELOG.md`.
- Check that `fmugen` is free on PyPI before the first upload. Until then, install it from a checkout or a built wheel.

### 2.3 ✅ Dependency hygiene (fixed)
fmugen required PySide6, plotly, FMPy, colorama, coloredlogs, toml, typing-extensions, pyzmq and an exact `protobuf==5.27.3`, and imported none of them.

**Fixed:** fmugen is installed into the user's model venv, and the FMU runs with that venv. So its dependencies are exactly what UniFMU 0.14's Python backend imports: `protobuf==5.27.3` and `pyzmq`. Everything else is gone, and FMPy is a dev dependency for the tests. Inside the FMU, `requirements.txt` lists those two plus `[model] requirements`. UniFMU's own file also listed FMPy, colorama, coloredlogs and toml, which the backend doesn't use.

Remaining risk: the exact `protobuf==5.27.3` pin lands in the user's environment and can conflict with other packages that pin protobuf (TensorFlow, grpcio, …). The pin comes from UniFMU's generated `*_pb2.py` files. Regenerating the schemas, or testing a range like `protobuf>=5.27,<6`, would loosen it.

### 2.4 🟡 Python version
`requires-python = ">=3.13"` and `.python-version = 3.13`, but nothing needs 3.13:
- `tomllib` needs 3.11.
- `Path.is_relative_to` needs 3.9.
- `match` in the UniFMU backend needs 3.10.

Lowering the floor to **3.10 or 3.11** (with `tomli` as a fallback for 3.10) widens adoption a lot, since many scientific and industrial environments are still on 3.10–3.12. Add a CI matrix over 3.10–3.13 on Windows, Linux and macOS.

### 2.5 🔴 Licensing
- There is no `LICENSE` file at the root. Without one the code is "all rights reserved" and cannot legally be reused.
- UniFMU is no longer redistributed in the repo, but every generated FMU contains UniFMU's binaries and backend (MIT, INTO-CPS Association). Say so in the docs, so users who ship FMUs include UniFMU's licence.
- Example code (simple-pid, RC_BuildingSimulator, FilterPy) is credited in the README. `rc_simulator/LICENSE` is present; check that each vendored example carries its licence file.
- Generated FMUs include fmugen's runtime. State the licence that applies to the generated FMU (a permissive licence, or an explicit exception), so users can ship FMUs commercially.

---

## 3. Portability of the generated FMUs

This matters most for "handle all models, run anywhere".

### 3.1 ✅ The Python interpreter inside the FMU (fixed)
Before: `launch.toml` used `python3` on Linux and macOS and, with `--python`, the builder's interpreter on Windows only. Nothing made sure that interpreter had the backend's and the model's packages.

**Fixed, by design:** fmugen is installed into the model's virtual environment and run from there. That environment already has the model's packages, and it gets the backend's packages as fmugen's dependencies. `launch.toml` always points at that environment's interpreter (`sys.executable`) for the current OS. `--python` and `--vendor` were removed. The build probe runs in the same environment the FMU will use, so a successful build means the FMU's imports work.

By default, then, an FMU runs on the machine where it was built. For other machines:
- **`--vendor`**: wheels of every requirement go into the FMU. A launcher installs them offline into a cached venv on its first run. Wheels for other platforms and Python versions come from `--platform` / `--python-version`. The target needs Python. [verified with FMPy through UniFMU]
- **`--compile pyinstaller|nuitka`**: the backend, the model, its packages and the interpreter are frozen into an executable. The FMU ships no `.py` files and needs no Python, but runs only on the OS it was built on. Nuitka compiles to machine code, which protects the source much better than PyInstaller's bytecode. [both verified with FMPy through UniFMU]

Still open: building compiled FMUs for several OSes needs one build per OS plus a step that merges them into one `.fmu`.

### 3.2 🟡 Module name clashes
`RESERVED_MODULES` protects `model`, `backend`, `main`, … but not the standard library:
- At build time, `load_module` registers `sys.modules[model_path.stem]`.
- At runtime, `fmugen_model/` is placed **first** on `sys.path`.

So a user file called `logging.py`, `json.py`, `random.py`, `types.py`, `queue.py` or `test.py` would shadow the standard library for the backend itself (`fmugen_runtime` imports `json` and `logging`). Check entry and source names against `sys.stdlib_module_names`. Either reject them, or append the model dirs to `sys.path` after the backend's imports have run.

---

## 4. Model coverage ("can it handle every model?")

What is already supported is broad:
- functions and classes
- attributes, properties and setter methods
- positional-only arguments of C extensions
- `setup` calls
- `kind = "function"`
- arrays and numpy
- enums
- clocks
- models built by a factory (`[model] create`, e.g. `from_pretrained`)
- inputs converted before the call (`convert = "torch:tensor"`) and array outputs from any library (torch tensors)
- factory functions (a function entry with `call`), constants computed by a call (`{ call = "…" }`), and tuple/dict arguments built from several variables (`to = "arg:NAME[i]"`)
- 20 tested PyPI models and 6 small neural networks (Chronos-Bolt, Silero VAD, Granite TTM, an SB3 PPO controller, a surfaces ONNX surrogate, TorchANI), all giving results identical to calling them directly; see `docs/tested-models.md`

These are the gaps found:

| Gap | Effect | Suggestion |
|---|---|---|
| ✅ **NamedTuple returns** were named `y0, y1` instead of their field names | Fixed: field names, `from = "return:<field>"` (found with TorchANI's `SpeciesEnergies`) | — |
| ✅ **Nested dicts / objects** (`{"zone": {"T": 21}}`, `result.state.T`) | Fixed: outputs named with dots (`zone.T`), `from = "return:zone.T"` walks dict keys, positions and attributes (also for `attr:`). `init` reads nested dict literals from the code, and nested dicts/NamedTuples/dataclasses with `--probe`. Checked with highway-env's `info["rewards"]`. Also fixed while testing it: FMI 3 `init` wrote a variable named `time`, which `build` rejects; it is now `model_time` | — |
| ✅ **ML models: factories and tensors** (found with Chronos-Bolt) | Was: a model created by `from_pretrained` couldn't be described; `torch.Tensor` inputs and outputs weren't handled | Fixed: `[model] create` / `init --create`, `convert` (set by `init` from torch/JAX/TensorFlow annotations), tensor outputs. ✅ Also fixed: `--hf-weights` (on with `--vendor`/`--compile`) puts the Hugging Face models into the FMU, which loads them offline (checked with Chronos-Bolt and the SB3 policy, empty cache, `HF_HUB_OFFLINE=1`) |
| ✅ **Number-like values:** 0-d numpy arrays (found with SB3's action), `numpy.float16`, `Decimal`, `Fraction`, `pint` quantities | Fixed: anything with `__float__`/`__index__` that isn't an array is an FMI value. pint outputs are read in the variable's `unit` (`init --probe` writes it), and `convert = "pint"` passes inputs as quantities. Checked with `fluids.units` (`Reynolds`, `head_from_P`) in FMI 2 and 3 | — |
| ✅ **Lists in FMI 2** | Fixed: an array variable with fixed `dimensions` becomes one scalar per element (`x[1]`, `x[1,2]`, FMI 2 "structured" naming), and the model still gets the whole array. No option is needed: `init` now finds arrays for FMI 2 too. Checked with `ahrs` Madgwick (FMI 2 was ✗ before) | — |
| ✅ **pandas Series / DataFrame / xarray** returns | Fixed: a Series (index labels), a one-row DataFrame (columns) and an xarray Dataset of single values (data variables) become named outputs, read with `from = "return:<label>"`. `[time]` also takes `{ source, epoch }` to pass a date-time. Checked with pvlib `get_solarposition` in FMI 2 and 3. No published model returning an xarray Dataset was found: unit tests only | — |
| ✅ **dataclass / pydantic / attrs inputs** (`step(self, u: Inputs)`) | Fixed: `to = "arg:u.temp"` binds a field. The object is built from the argument's default (copied with the fields replaced) or from its annotated class. `init` writes one variable per field (`--start u.temp=…` for fields without a default). Checked with pythermalcomfort `sports_heat_stress_risk` (`sport: _SportsValues`) in FMI 2 and 3. No published model with a pydantic or attrs argument was found: unit tests only | — |
| **Generators / coroutines** (`yield`-based models, `async def step`) | Unsupported (left open: no published generator or async model was found to test against; simpy models already work through a factory calling `env.run(until=…)`) | Drive with `next()`/`send()`, or `asyncio.run` per step |
| ✅ **`Optional[X]` / `X \| None` annotations** without a default | Fixed: `Optional`, `Union[X, None]` and `X \| None` (also as string annotations) are unwrapped, so int/bool keep their type. Arguments that default to `None` stay constants, keeping the model's own "not given" behaviour (checked with `fluids.friction:material_roughness`). No published model with a no-default `Optional` was found, so this is covered by unit tests | — |
| ✅ **Multiple entry points / composite models** | Fixed: a `[composite]` config lists other fmugen configs and `"part.output -> part.input"` connections; the parts run in order in one FMU, with state and reset covering all of them. Checked with a pvlib chain of three functions in FMI 2 and 3. Not yet: `--compile` of a composite, and parts with clocks or structural parameters | — |
| ✅ **Models that need files** (`weather.csv`) | Fixed: `[model] cwd` runs the model (import, setup, every call) in the FMU's copy of the config folder, so relative paths work, and the importer's working directory is put back afterwards. Data files go in `sources`. `init` adds both when a string in the model or a `--start` value names a file next to the config, and `init` itself runs in that folder. Compiled FMUs keep the data files. Checked with pvlib `read_tmy3` on its own TMY3 file | — |
| ✅ **Int outputs** always inferred as Real (by design) | Kept, and `init --probe` now says so on each output that was an int, suggesting `type = "Integer"` for counts | — |
| ✅ **`Boolean` coercion from strings** (`coerce("Boolean", "false")` gave `True`) | Fixed: `true/false/1/0/yes/no/on/off` are parsed (any case), other strings raise | — |
| ✅ **Very large arrays** | Fixed: `set_values` reads with an index instead of `values.pop(0)` (was O(n²)) | — |
| ✅ **Stateful module-level globals** (functions with `global` counters) | Fixed: `[model] globals = ["module:NAME"]` are put back to their import-time values on reset and saved with the FMU state. `init` lists the number/string/array globals that the modules reached from the entry rebind. Checked with pythermalcomfort JOS3 (`PRE_SHIV`): rollback repeats exactly only with it. Instances in one process still share globals | — |
| ✅ **Models without pickling support** (e.g. anything holding an ONNX Runtime `InferenceSession`: Silero VAD, surfaces) | Was: state save/restore disabled | Fixed: `cloudpickle` fallback, and `save_state = [attributes]` saves only what can be pickled (written by `init`). Silero VAD now rolls back correctly through UniFMU. ✅ Also fixed: `dill` is tried after `cloudpickle`, `[model] globals` are saved, and the FMU state includes the global random generators (`random`, numpy, torch), so a stochastic SB3 policy repeats its actions after a restore |

---

## 5. Correctness and robustness (code-level)

### 5.1 CLI and build (`__main__.py`)
- ✅ Fixed: neither `build` nor `init` runs user code by default. `build` imports the model to check the config. `init` reads signatures and source code (`fmugen/static.py`): return statements, attributes the step method and the methods it calls assign, annotations, and the `x_prev` state pattern. Calling the model is opt-in, with `init --probe`. On the published models, reading the code gives the same outputs as the probe for all 11 scalar functions and the RC building. It can't know array sizes, results built at runtime, code without Python source, unannotated property types or `save_state`; the config marks those with commented lines. A timeout for the `--probe` call would still help with slow models.
- Missing commands that users will expect (see §8): `fmugen check`, `fmugen run`, `fmugen inspect`.
- `main()` only catches `FileExistsError` and `InterfaceError`. An exception from user code during `build` (e.g. at import) prints a raw traceback. That is acceptable, but a `--debug` flag would let the default path show a short message.

### 5.2 Config (`config.py`)
- `TYPE_NAMES[2]` maps `"Float64"` to Real and `"Int32"` to Integer, but FMI 2 configs using `Float32`/`Int64` give a clear error. Consider *widening* (`Int64` becomes Integer with a range warning) so one config works for both versions.
- `normalize()` takes `description` from the first docstring line. Long or markdown docstrings end up in the XML. Truncate them to a reasonable length.
- `_check_value` rejects `start = 1` for a `Boolean`. That is correct, but the error could suggest `true`.
- There is no `spec_version` check in the runtime. `interface.json` has `"spec_version": 1`, but `Engine` never reads it. Check it, so an FMU built with an older fmugen fails clearly once the spec changes.
- The config schema is only enforced in Python. Publish a **JSON Schema** for `fmugen.toml` (Taplo / Even Better TOML picks it up), which gives autocompletion and validation in editors for free.

### 5.3 Inference (`interface.py`)
- `_local_sources` scans **all** of `sys.modules` for files under `config_dir`. If the config dir contains a `.venv` that isn't named `site-packages`, or a `build/` copy, extra directories are pulled in. Also exclude `.venv`, `venv`, `env`, `build`, `dist`, and hidden directories.
- `load_module` registers the module under its bare stem. See §3.2 for the clash risk.
- `_pick_entry` only considers objects defined in the module. A model file that only re-exports (`from .core import Model`) gives "found: none". Fall back to public classes and functions in `__all__`.
- The `_prev` suffix is the only state convention. Also recognise `x_old`, `x0`/`x`, `last_x`, and a `state` dict that is passed in and returned.

- ✅ Fixed: `init` crashed after importing `transformers`. Cleaning up imports read `__file__` with `getattr`, which makes lazy modules import optional parts (here one needing `torchvision`). It now reads `__dict__`.

### 5.4 Runtime (`templates/fmugen_runtime.py`)
- `do_step` doesn't check that `current_time` matches `self.time`. After a rollback that is valid, but a mismatch outside rollback could be logged as a warning.
- `tolerance` is stored but never forwarded. Allow `[time] tol = "tolerance"` so ODE-based models (scipy `solve_ivp`) can use it.
- `stop_time` is also not offered as a time source. Add `"stop_time"` and `"start_time"` to `TIME_SOURCES`.
- `fmi2SetDebugLogging` / `fmi3SetDebugLogging` ignore `categories`. Honour them, at least for `logAll` / `logEvents` versus status categories.
- `Status.discard` is never used. Let models signal "step rejected, retry smaller" (e.g. by raising `fmugen.Discard` or returning a configured flag). Variable-step master algorithms rely on it.
- `deserialize` uses `pickle.loads` on bytes from the importer. That is normal for FMUs, but document that FMU state blobs must come from trusted sources.
- `reset()` drops `self.obj` without calling the model's `terminate` method. If the object holds resources (serial ports, files), they leak until garbage collection.
- ✅ `stdout` / `print()` in user code can now be forwarded to the importer's log with `build --capture-output` (off by default; see §5.7).

### 5.5 modelDescription (`description.py`)
- The GUID or instantiation token comes from `uuid4()` and `generationDateAndTime` from `now()`, so builds are not reproducible. Derive the GUID from a hash of `interface.json` plus the sources, and respect `SOURCE_DATE_EPOCH`. This also gives a stable GUID for unchanged models, which some importers cache on.
- FMI 2 `UnitDefinitions` only declare names. Adding `BaseUnit` (SI exponents) would let importers check and convert units. A small table for common units (K, Pa, W, m, s, kg, …) goes a long way.
- `displayUnit`, `relativeQuantity`, `unbounded`, `reinit` and `<Annotations>` are not exposed. Allow arbitrary extra attributes per variable as an escape hatch.
- FMI 3 terminals and icons (`terminalsAndIcons/`) and FMI 3 `<Annotations>` are not supported. Low priority.

### 5.6 FMI feature coverage
These are limited by UniFMU's Python backend and documented in `docs/fmi.md`:
- No Model Exchange.
- No directional or adjoint derivatives.
- No intermediate update or early return.
- No Scheduled Execution.

They are acceptable for Python co-simulation. For "all models", Model Exchange is the one people will ask for, because it lets ODE right-hand-side functions be used with the importer's own solver. See §8.

### 5.7 🟠 UniFMU 0.14 hangs when the model prints a lot
Found while testing Chronos-Bolt. When the FMU's Python process writes more than about 4 KB to stdout/stderr, UniFMU's native library panics (`zeromq-0.4.1/src/rep.rs:168:40: not yet implemented`) and the importer waits forever, with no error. [verified]
- 3,900 characters printed: fine. 4,200: crash. Splitting the output into small flushed writes still crashes, so it is the total amount.
- Message size is not the cause: a 160 KB array output and a 70,000-character log message sent through the FMI logger both work.
- Typical triggers: library warnings, progress bars (Hugging Face loading prints both), tracebacks printed by the model, and the backend's root logging handler echoing large log records.

**Workaround (done):** `fmugen build --capture-output`. Inside UniFMU's backend, the runtime redirects file descriptors 1 and 2 to a temporary file and sends what was written to the importer's log as `[output]` messages after each call. It also catches output from C code. Off by default, so prints still go to the console. A regression test runs the FMU in a subprocess with a timeout.

Still open:
- Report it upstream to UniFMU, with the small reproduction (a function that prints 5 KB).
- The default is still exposed: a model that prints a lot hangs unless built with the flag. `init --probe` could suggest the flag when its probe call prints a lot.

---

## 6. Tests and quality

Strengths:
- Real UniFMU runs for both FMI versions.
- FMPy validation of `modelDescription.xml`.
- Coverage of clocks, arrays, state and tunables.
- The tested-models document.

Gaps:
- **No CI.** Add GitHub Actions with Windows, Linux and macOS × Python 3.10–3.13. Run unit tests on every push and the slower UniFMU runs nightly or on `main`.
- **No test runs from an installed wheel.** That is why §2.1 went unnoticed.
- **No cross-validation with other importers.** FMPy is the only importer used. Add the [FMI Compliance Checker / fmusim from Reference-FMUs](https://github.com/modelica/Reference-FMUs) and, optionally, OMSimulator. Different importers call functions in different orders.
- The 20 PyPI models in `docs/tested-models.md` are not automated. Turn them into an opt-in `pytest -m pypi` suite (installs each package, runs `init` → `build` → simulate), so regressions in the "works on real models" promise are caught.
- **Property-based tests** (Hypothesis) for `render_toml` → `load_config` round-trips and for `coerce` / `reshape` / `flatten`.
- The tests take 120 s. Mark the UniFMU subprocess tests `@pytest.mark.slow` so the fast loop stays under ~10 s.
- No linter, formatter or type checker is configured. Add `ruff` (lint and format) and `pre-commit`. Type hints are sparse, so `mypy`/`pyright` in basic mode on `src/fmugen` would catch dict-shape mistakes in the interface spec. A `TypedDict` for the spec would document it too.

---

## 7. Repository hygiene and documentation

- `.git` is 91 MB (a 75 MB pack). ✅ `tools/unifmu.exe` (23 MB) was removed from every commit of `tomas` with `git filter-branch` (same final tree, `main` untouched); it takes effect for others only after a force-push of `tomas`. Most of the size is older: seven generated `.fmu`/`.zip` files of ~26 MB and a 71 MB `FMUs/ORIGINAL.fmu/binaries/linux64/unifmu.so` in early commits shared with `main`. Removing those means rewriting `main` too, or publishing from a fresh history.
- ✅ `.idea/` is no longer tracked (`git rm -r --cached .idea`); the files stay local and ignored.
- `image.png` (75 KB) at the root isn't referenced obviously. Move it to `docs/img/` or delete it.
- `.gitignore`: add `.venv/`, `dist/`, `build/`, `*.egg-info`, `.pytest_cache/`, `*.fmu` (outside examples).
- The `src/fmugen/__init__.py` docstring still says "UniFMU (FMI 2.0 Co-Simulation) FMUs". Update it for FMI 3. Also expose `__version__`.
- Missing community files for open source: `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and PR templates, `CHANGELOG.md`, `CITATION.cff` (useful for academic users; the README already cites a paper).
- The docs are excellent but spread over 6 pages plus a 585-line manual. Consider publishing them with MkDocs Material on GitHub Pages, with search.
- The README "Requirements" section only mentions uv. Once on PyPI, add `pipx install fmugen` / `uv tool install fmugen`.
- Docker demo:
  - It is FMI 2 only (`FMU2Slave`) and maps only Real/Integer/Boolean/String.
  - It uses Python 3.11 while the project pins 3.13.
  - Mounting `/var/run/docker.sock` into the Streamlit container gives that container root-equivalent access to the host. Say so in `docker/Readme.md` and recommend not exposing port 8501 publicly.

---

## 8. Suggested improvements and new features

Ordered by value to an open-source user base.

### Tier 1: before the first public release
1. ✅ Rename the distribution and trim dependencies (done). **Add a LICENSE** and third-party notices (§2.5), then publish to PyPI.
2. **CI matrix** on 3 OSes × Python 3.10–3.13, plus a "build from installed wheel" smoke test.
3. **Lower `requires-python`** to 3.10 or 3.11.
4. ✅ **Neither build nor init runs the model by default** (done; `init --probe` to call it). Still useful: a timeout for the `--probe` call.
5. **Reject model module names that shadow the standard library.**

### Tier 2: portability ("an FMU that runs anywhere")
6. ✅ **Self-provisioning FMU runtime from vendored wheels.** Done: `--vendor` (§3.1).
7. ✅ **Multi-platform vendoring.** Done: `--platform` / `--python-version` (§3.1). Also done: `--compile pyinstaller|nuitka`. Next: merging compiled builds from several OSes into one FMU.
8. **`--embed-python`** (opt-in): a python-build-standalone interpreter for fully offline, self-contained FMUs.
9. **Reproducible builds**: a deterministic GUID, `SOURCE_DATE_EPOCH`, and sorted zip entries with fixed timestamps.

### Tier 3: model coverage ("handle every model")
10. ✅ NamedTuple field names and 0-d arrays (done). Still to do: nested dict and object outputs flattened with dotted names, pandas Series, pint quantities, anything with `__float__` (§4).
11. **FMI 2 array expansion** (`x[3]` becomes `x_1..x_3`) so array models work for FMI 2 importers too.
12. **Structured inputs**: build dataclass, pydantic or attrs arguments from flat FMU variables.
13. **Generator and async model support.**
14. **`cwd` / data-file support** for models that open relative paths.
15. **Discard support**, so a model can reject a step.
16. **Tolerance, start-time and stop-time time sources.**
17. ✅ **Print capture** to the FMI log: `build --capture-output`.
18. ✅ **Pickling fallbacks** (done: `cloudpickle`, and `save_state = [attributes]` chosen by `init`). Still possible: `dill`, saving module globals and global RNG states.
19. **Model Exchange (FMI 2 and 3) for ODE models**: `[model] kind = "ode"` with `derivatives = "return"` and continuous states. UniFMU's Python backend does not support ME today, so this needs an upstream contribution or a different native wrapper. It is the most-requested FMI capability after co-simulation.
20. **Internal solver helper**: `[model] integrate = "rk4" | "scipy:RK45"` turns an ODE right-hand side `f(t, x, u)` into a co-simulation FMU, with internal sub-steps and the tolerance passed in. It covers ODE models now without needing ME.
21. **Wrappers for other model formats**: Jupyter notebooks (`.ipynb` entry via `nbformat`), scikit-learn, ONNX, PyTorch or joblib-pickled ML models (`[model] kind = "sklearn"` calls `predict` with inputs as features). This would be a large draw for data-driven and digital-twin users. Partly done: six published networks on PyTorch and ONNX Runtime work unmodified (factories, computed constants for downloaded weights, tensor conversion, tuple arguments). Still to do: bundling model weights into the FMU, and trying scikit-learn and ONNX models.

### Tier 4: developer experience
22. **`fmugen check fmugen.toml`**: validate the config and, on request, run the model once (the old build probe) without packaging, with a readable table of the variables.
23. **`fmugen run model.fmu --stop-time … --input in.csv --plot`**: a thin FMPy wrapper so users don't need to learn FMPy to try their FMU.
24. **`fmugen inspect model.fmu`**: show `interface.json`, variables, platforms, Python requirements and the fmugen version that built it.
25. **`fmugen init --interactive`**: a TUI or questions that ask about the ambiguous choices (which method, units, which attributes are outputs) instead of making the user edit TOML.
26. **Units from annotations and docstrings**: read `Annotated[float, "K"]`, pint annotations, or numpydoc `Parameters` sections to fill `unit` and `description` automatically.
27. **JSON Schema for `fmugen.toml`** for editor completion.
28. **A Python API** (`fmugen.build(model=..., config=dict(...))`) documented as public, so fmugen can be used from notebooks and other tools.
29. **Watch mode** (`fmugen build --watch`) for a fast edit → build → simulate loop.
30. **Remote and distributed FMUs**: UniFMU supports distributed backends (`logUnifmuMessages` is already declared). Expose `fmugen build --distributed` to produce an FMU whose Python side runs on another host or container. This fits the Docker/OPC UA demo well.
31. **Plugin hooks** (entry points) for custom type converters (`fmugen.converters`), so third parties can add support for their own result types without changing fmugen.

---

## 9. What is already good (keep it)

- **Not changing the user's code** is the right core principle, and the code sticks to it. Every adaptation (positional-only args, setters, `kind = "function"`, setup calls) is done in config, never in the user's code.
- **One engine and two thin adapters.** FMI 2 and FMI 3 behaviour can't drift apart.
- **Errors explain what to do**, e.g. "pass --call METHOD", "use model.py:Name", "arrays need --fmi 3".
- **`fmugen init`'s probe call** discovers outputs and pickling problems; `build` checks the config against the imported code without running it.
- **`isolated_imports()`** keeps repeated builds and tests clean.
- **Generated configs are commented** and explain each guess.
- **Documentation**: function-by-function FMI behaviour, packaging internals, a tested-models log. This is better than most comparable tools.
- **Tests run through real UniFMU** rather than only mocking.
