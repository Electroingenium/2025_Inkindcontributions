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
| 3 | ✅ Fixed | The FMU's Python was unclear. By design, fmugen is installed in the model's venv and the FMU runs with that venv's Python |
| 4 | ✅ Fixed | Placeholder package metadata and bloated dependencies. The package is now `fmugen`, depending only on what the FMU's backend needs |
| 5 | 🟡 Medium | `requires-python >= 3.13` excludes many users. The code needs about 3.11 (`tomllib`) and the FMU runtime needs 3.10 (`match` in the backend) |
| 6 | 🟡 Medium | The build-time probe always runs the model. That is unsafe for hardware or network models (e.g. tclab) and there is no `--no-probe` option |
| 7 | 🟡 Medium | Some inference gaps reduce the "works on any model" coverage (see §4) |
| 8 | 🟡 Medium | An 89 MB `.git` history (the removed `unifmu.exe` and binaries are still in it). `.idea/` is tracked even though `.gitignore` lists it |
| 9 | 🟢 Low | Builds are not reproducible (random GUID and current timestamp), there is no CI, and a few docstrings are stale |

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

Consequence: an FMU runs on the machine where it was built, as long as that environment exists. Running it on another machine means rebuilding it there from an equivalent environment (`resources/requirements.txt` lists what it needs). Shipping FMUs to other machines is a non-goal for now. See §8 if that changes.

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
- 20 tested PyPI models

These are the gaps found:

| Gap | Effect | Suggestion |
|---|---|---|
| **NamedTuple returns** are named `y0, y1` instead of their field names [verified: a `namedtuple("R", "power temp")` gives `y0`/`y1`] | Poor names. The user must rename them by hand | Check `hasattr(result, "_fields")` before the tuple branch and use `return:<field>` |
| **Nested dicts / objects** (`{"zone": {"T": 21}}`, `result.state.T`) | Skipped during inference. The runtime `pick()` only goes one level deep for dicts | Flatten as `zone.T` (FMI `structured` naming), with `from = "return:zone.T"` resolved through mappings *and* attributes |
| **0-d numpy arrays**, `numpy.float16`, `decimal`, `Fraction`, `pint` quantities | Not seen as FMI values (`_fmi_value`), so they are silently left out | Accept anything that defines `__float__` / `__index__` (and `.magnitude` for pint, using its units for `unit`) |
| **Lists in FMI 2** | Dropped entirely | Offer `expand_arrays = true`, which turns `x[3]` into the scalars `x_1, x_2, x_3` (FMI 2 `structured` naming) |
| **pandas Series / DataFrame / xarray** returns | Skipped | Series becomes named outputs (index → names). DataFrame row becomes outputs |
| **dataclass / pydantic / attrs inputs** (`step(self, u: Inputs)`) | Not inferred | Build the argument object from flat variables: `to = "arg:u.temp"` |
| **Generators / coroutines** (`yield`-based models, `async def step`) | Unsupported | Drive with `next()`/`send()`, or `asyncio.run` per step |
| **`Optional[float]` / `float \| None` annotations** without a default | `_type_info` gets `annotation=Optional[...]` and falls back to Real 0.0. Probably fine, but int/bool unions are lost | Unwrap `typing.get_args` |
| **Multiple entry points / composite models** | One entry per FMU | Allow several `[model.<name>]` blocks wired together, or document using an importer for that |
| **Models that need files** (`weather.csv`) | They must sit under the config dir in `sources`, and the code must open them relative to `__file__` | Add `[model] data = [...]` and a `cwd = "model"` option that `chdir`s to `fmugen_model/` during calls (many research models open relative paths) |
| **Int outputs** always inferred as Real (by design) | Fine, but surprising | Keep it, and note it in the generated comment (already partly done) |
| **`Boolean` coercion from strings** (`coerce("Boolean", "false")` gives `True`) | Wrong value if a model returns `"false"` | Parse common string forms, or raise |
| **Very large arrays** | `set_values` uses `values.pop(0)`, which is O(n²) | Use an index or iterator |
| **Stateful module-level globals** (functions with `global` counters) | `fmi2Reset`/`fmi3Reset` don't reload the module, so state survives a reset, and `serialize` doesn't save globals | Document it, or offer `reset = "reload"` that re-imports the model package |
| **Models without pickling support** | State save/restore is disabled (handled well by the probe) | Try `copy.deepcopy` and `dill`/`cloudpickle` as fallbacks before giving up. Add a `__getstate__` hook option in the config (`state = "attr:a,b,c"` to snapshot only some attributes) |

---

## 5. Correctness and robustness (code-level)

### 5.1 CLI and build (`__main__.py`)
- The **probe always executes user code at build time**, both in `infer_config` and in `_probe`. For hardware (tclab), network or licence-server models, or slow models, this has side effects or hangs. Add `--no-probe` (assume `can_get_and_set_state = false` or let the config decide) and a probe timeout.
- `build()` writes `interface.json` twice: once before the probe and once after it with `can_get_and_set_state`. That is fine, but if the probe raises, the error has no "the model built but the probe failed" context. Point to `--no-probe`.
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

### 5.4 Runtime (`templates/fmugen_runtime.py`)
- `do_step` doesn't check that `current_time` matches `self.time`. After a rollback that is valid, but a mismatch outside rollback could be logged as a warning.
- `tolerance` is stored but never forwarded. Allow `[time] tol = "tolerance"` so ODE-based models (scipy `solve_ivp`) can use it.
- `stop_time` is also not offered as a time source. Add `"stop_time"` and `"start_time"` to `TIME_SOURCES`.
- `fmi2SetDebugLogging` / `fmi3SetDebugLogging` ignore `categories`. Honour them, at least for `logAll` / `logEvents` versus status categories.
- `Status.discard` is never used. Let models signal "step rejected, retry smaller" (e.g. by raising `fmugen.Discard` or returning a configured flag). Variable-step master algorithms rely on it.
- `deserialize` uses `pickle.loads` on bytes from the importer. That is normal for FMUs, but document that FMU state blobs must come from trusted sources.
- `reset()` drops `self.obj` without calling the model's `terminate` method. If the object holds resources (serial ports, files), they leak until garbage collection.
- `stdout` / `print()` in user code is not forwarded. Many research models `print` instead of `logging`. Optionally redirect `sys.stdout` to the logger during calls (`[model] capture_print = true`).

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

- `.git` is 89 MB, mostly the removed `tools/unifmu.exe` and UniFMU binaries. Consider rewriting history (`git filter-repo`) before going public so clones stay small.
- `.idea/` is partly tracked even though `.gitignore` lists it. Remove it with `git rm -r --cached .idea`.
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
4. **`--no-probe`** and a probe timeout.
5. **Reject model module names that shadow the standard library.**

### Tier 2: portability ("an FMU that runs anywhere")
6. **Self-provisioning FMU runtime** (only if FMUs must run on other machines). A launcher could recreate the environment from `requirements.txt` on first run. This is out of scope for now (§3.1).
7. **Multi-platform vendoring** (same condition): wheels for target platforms inside the FMU, for offline installs.
8. **`--embed-python`** (opt-in): a python-build-standalone interpreter for fully offline, self-contained FMUs.
9. **Reproducible builds**: a deterministic GUID, `SOURCE_DATE_EPOCH`, and sorted zip entries with fixed timestamps.

### Tier 3: model coverage ("handle every model")
10. NamedTuple field names, nested dict and object outputs flattened with dotted names, pandas Series, pint quantities, 0-d arrays, anything with `__float__` (§4).
11. **FMI 2 array expansion** (`x[3]` becomes `x_1..x_3`) so array models work for FMI 2 importers too.
12. **Structured inputs**: build dataclass, pydantic or attrs arguments from flat FMU variables.
13. **Generator and async model support.**
14. **`cwd` / data-file support** for models that open relative paths.
15. **Discard support**, so a model can reject a step.
16. **Tolerance, start-time and stop-time time sources.**
17. **Print capture** to the FMI log.
18. **Pickling fallbacks** (`dill`, `cloudpickle`, `deepcopy`, or user-selected attributes) so more models keep rollback support.
19. **Model Exchange (FMI 2 and 3) for ODE models**: `[model] kind = "ode"` with `derivatives = "return"` and continuous states. UniFMU's Python backend does not support ME today, so this needs an upstream contribution or a different native wrapper. It is the most-requested FMI capability after co-simulation.
20. **Internal solver helper**: `[model] integrate = "rk4" | "scipy:RK45"` turns an ODE right-hand side `f(t, x, u)` into a co-simulation FMU, with internal sub-steps and the tolerance passed in. It covers ODE models now without needing ME.
21. **Wrappers for other model formats**: Jupyter notebooks (`.ipynb` entry via `nbformat`), scikit-learn, ONNX, PyTorch or joblib-pickled ML models (`[model] kind = "sklearn"` calls `predict` with inputs as features). This would be a large draw for data-driven and digital-twin users.

### Tier 4: developer experience
22. **`fmugen check fmugen.toml`**: validate the config and run the probe without packaging, with a readable table of the variables.
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
- **The build probe** catches broken configs and pickling problems before the user ships an FMU.
- **`isolated_imports()`** keeps repeated builds and tests clean.
- **Generated configs are commented** and explain each guess.
- **Documentation**: function-by-function FMI behaviour, packaging internals, a tested-models log. This is better than most comparable tools.
- **Tests run through real UniFMU** rather than only mocking.
