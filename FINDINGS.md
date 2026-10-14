# fmugen review: open items and feature ideas

This file combines two reviews of the whole repository:

| Review | Branch | Scope |
|---|---|---|
| 2026-10-05, status updated 2026-10-06 | `tomas` @ `30d827b` … `8aa4903` | All first-party source, the UniFMU integration, tests, docs, examples, the Docker demo, packaging and repo hygiene, with a focus on **portability, installability and how wide a range of models fmugen handles**. Checked by reading the code, running the tests, building the wheel and probing model shapes with `fmugen init`. |
| 2026-10-14 | `dev` @ `e3276ac` … | All of `src/fmugen` again (CLI, config, XML writer, composite, distribute, runtime, adapters, launcher), the inference code (`interface.py`, `static.py`) and the Docker demo, looking for bugs, gaps and features. |

- **[verified]** means the finding was reproduced (UniFMU 0.14.0, the project's uv environment, Windows).
- **[code]** means it was found by reading the code.

Problems in UniFMU and FMPy themselves, and fmugen's workarounds for them, are in [docs/unifmu-limitations.md](docs/unifmu-limitations.md) and [docs/fmpy-limitations.md](docs/fmpy-limitations.md), not here.

---

## 1. Summary

The core design is sound. The user's code is never touched: a sidecar `fmugen.toml` holds the mapping, one runtime engine sits behind thin FMI 2 and FMI 3 adapters, and the error messages say what to do. The documentation is thorough, and the tests run real FMUs through UniFMU for both FMI versions.

What still stands between fmugen and an open-source release is **distribution**, not the core logic:

| Severity | Item | Section |
|---|---|---|
| 🟠 | No test that installs the built wheel | [2.5](#25-tests-and-quality) |
| 🟡 | `--vendor` FMUs start `python` on Windows, which may be the Microsoft Store stub | [2.2](#22-portability) |
| 🟢 | Model coverage gaps: generator models, notebooks, scikit-learn and ONNX files | [2.3](#23-model-coverage) |

---

## 2. Open items

### 2.1 Before a public release
- **Package metadata:** no project URLs (no public repository yet), and a static version (consider `hatch-vcs` and a `CHANGELOG.md`). Check that the name `fmugen` is free on PyPI before the first upload; until then fmugen is installed from a checkout or a built wheel. Once on PyPI, the README can add `pipx install fmugen` / `uv tool install fmugen`.

### 2.2 Portability
- **🟡 `--vendor` on Windows runs `python`** (`python3` elsewhere). On a clean Windows machine `python` is often the App Execution Alias that opens the Microsoft Store. Prefer the `py -3` launcher when it exists, and let users choose the interpreter at runtime (e.g. `FMUGEN_PYTHON`). [code]
- **Multi-OS compiled FMUs.** `--compile` freezes for the OS it runs on. Shipping one FMU for several OSes needs one build per OS plus a step that merges their `resources/dist/` folders (`launch.toml` already has one entry per OS).
- **`--embed-python`** (opt-in): a python-build-standalone interpreter inside the FMU, for fully offline FMUs that keep their sources (unlike `--compile`).
- **Python floor.** `requires-python = ">=3.13"`. The build side needs 3.11 (`tomllib`, `datetime.UTC`, `contextlib.chdir`, `hashlib.file_digest`) and the runtime inside the FMU 3.10 (`types.UnionType`). **Decision (2026-10-14): it stays at 3.13.**

### 2.3 Model coverage
Already supported, each checked with published models ([docs/tested-models.md](docs/tested-models.md) and its later rounds): functions and classes; attributes, properties and setter methods; positional-only arguments of C extensions; `setup` calls; `kind = "function"`; arrays and numpy (FMI 3 arrays, FMI 2 one scalar per element); enums; clocks; factories (`[model] create`, a function entry with `call`); computed constants (`{ call = … }`); converted inputs (`convert = "torch:tensor"`, `"pint"`); tuple, dict and dataclass/pydantic/attrs arguments; NamedTuple, nested dict/object, pandas and xarray results; anything with `__float__`; module globals; data files with `[model] cwd`; composite FMUs; Hugging Face weights bundled with `--hf-weights`.

Still missing:
- **Generators** (`yield`-based models, driven with `next()`/`send()`). `build` refuses them with a hint, because no published generator model was found to design the inputs (what `send()` gets) against; simpy models already work through a factory calling `env.run(until=…)`. Async models (`async def step`) are supported.
- **Other model formats:** Jupyter notebooks (`.ipynb` entry), scikit-learn (`kind = "sklearn"` calling `predict` with the inputs as features) and standalone ONNX files. Six published PyTorch and ONNX Runtime networks already work unmodified.
- **Inference:** a `state` dict passed in and returned (`def step(u, state): …; return y, state`) isn't recognised as a state; it needs `to = "arg:state[key]"` / `next = "return:1.key"` by hand.

### 2.4 Smaller code items
- **modelDescription:** FMI 3 terminals and icons aren't supported (low priority).

### 2.5 Tests and quality
- **No test from an installed wheel.** That is how the first review found a wheel that couldn't build anything.
- **FMPy is the only importer used.** Add [fmusim from the Reference FMUs](https://github.com/modelica/Reference-FMUs) and, optionally, OMSimulator: importers call functions in different orders.
- **The published-model tests are manual.** An opt-in `pytest -m pypi` suite built from the 46 configs in `docker/models/r3/*/fmugen.toml` would keep the promise that fmugen works on real published models checked.
- **Property-based tests** (Hypothesis) for `render_toml` → `load_config` round trips and for `coerce` / `reshape` / `flatten`.
- **No linter, formatter or type checker.** Add `ruff` (lint and format) and `pre-commit`. `pyright` or `mypy` in basic mode, plus a `TypedDict` for the interface spec, would catch dict-shape mistakes and document the spec.

### 2.6 Repository and docs
- **`.git` is about 75 MB.** Most of it is early commits shared with `main`: seven generated `.fmu`/`.zip` files (~26 MB) and a 71 MB `FMUs/ORIGINAL.fmu/binaries/linux64/unifmu.so`. Removing them means rewriting `main` too, or publishing from a fresh history.
- **Community files** for open source: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and PR templates, `CHANGELOG.md`, `CITATION.cff` (the README already cites a paper).
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
| 2 | **`fmugen run FMU --stop-time … [--input csv] [--plot]`**: a thin FMPy wrapper with FMI logging on, so errors are visible | Users get "failed with status 3" without a reason | new subcommand |
| 3 | **`fmugen inspect FMU`**: interface.json, the fmugen and UniFMU versions, the mode (venv / vendor / compile / distributed), platforms and requirements | Debugging FMUs received from others | new subcommand |
| 4 | **Record the fmugen version** (`fmugen.__version__`) in `interface.json` and in `generationTool` (`fmugen 0.1.0 + unifmu 0.14.0`) | Nothing in an FMU says which fmugen built it | `normalize`, `description.py` |
| 6 | **Units from annotations and docstrings** (`Annotated[float, "K"]`, pint annotations, numpydoc `Parameters`) | Fewer edits after `init` | `static.py` |
| 7 | **JSON Schema for `fmugen.toml`** | Completion and validation in editors (Taplo / Even Better TOML) | new file, from `VAR_KEYS` / `MODEL_KEYS` |
| 8 | **A documented Python API** (`fmugen.build(...)`, `fmugen.init(...)`); `build` already returns `(path, interface)` | Notebooks, scripts, other tools | `__init__.py` |
| 9 | **`init --interactive`**: ask about the ambiguous choices (which method, units, which attributes are outputs) instead of making the user edit TOML | Easier first config | `__main__.py` |
| 10 | **Merge compiled FMUs from several OSes** (`fmugen merge a.fmu b.fmu -o all.fmu`) ([2.2](#22-portability)) | `--compile` is single-OS | new subcommand |
| 11 | **Watch mode** (`fmugen build --watch`) | A fast edit → build → simulate loop | `__main__.py` |
| 12 | **Plugin hooks** (entry points, `fmugen.converters`) for custom result and input types | Third parties can add types without changing fmugen | runtime, inference |
| 13 | **`pytest -m pypi` suite** ([2.5](#25-tests-and-quality)) | Keeps the "works on real models" promise checked | `tests/` |

---

## 4. What is already good (keep it)

- **The user's code is never changed.** Every adaptation (positional-only arguments, setters, `kind = "function"`, setup calls, converters) is done in the config.
- **One engine and two thin adapters,** so FMI 2 and FMI 3 behaviour can't drift apart.
- **Errors say what to do,** e.g. "pass --call METHOD", "use model.py:Name", "arrays need --fmi 3".
- **`init` reads the code without running it,** and `--probe` finds what reading can't (array sizes, pickling); `build` checks the config against the imported code without running it.
- **`isolated_imports()`** keeps repeated builds and tests independent.
- **Generated configs are commented** and explain each guess.
- **The documentation** covers FMI behaviour function by function, packaging internals, UniFMU's and FMPy's limitations, and logs of the published models tried.
- **The tests run real FMUs through UniFMU,** not only mocks.
