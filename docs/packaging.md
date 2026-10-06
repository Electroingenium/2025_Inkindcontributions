# Packaging and runtime

- [CLI](#cli)
- [What `fmugen build` does](#what-fmugen-build-does)
- [Generated FMU layout](#generated-fmu-layout)
- [The FMU's Python environment](#the-fmus-python-environment)
- [FMUs for other machines](#fmus-for-other-machines)
- [Simulating](#simulating)
- [Project layout](#project-layout)
- [UniFMU version](#unifmu-version)

---

## CLI

Install fmugen into your model's virtual environment (`pip install fmugen`) and run it from there. `fmugen build` also needs the UniFMU 0.14.0 CLI (see [UniFMU version](#unifmu-version)). To work on fmugen itself, `uv sync` installs it in editable mode with the test dependencies.

### `fmugen init`

```
fmugen init MODEL [-o OUTPUT] [--call METHOD] [--fmi {2,3}] [--start NAME=VALUE ...] [--setup CALL ...] [--kind function] [--create CLASSMETHOD] [--force]
```

| Argument | Description |
|---|---|
| `MODEL` | `model.py`, `model.py:Name`, or `package.module:Name` (an installed module). |
| `-o, --output` | Where to write the config. Default: `fmugen.toml` next to the model (or in the current directory for an installed module). `-` prints it instead. The model file must be inside the config's folder. |
| `--call` | For classes: the method run on each step, when it isn't `step`/`do_step`/`update`/`__call__`/the only public method. |
| `--fmi {2,3}` | Write `fmi_version` into the config. With `3`, also infer arrays and Binary. |
| `--start NAME=VALUE` | Start value for an argument (a Python literal), e.g. one without a default; also used by `--probe`. Repeatable. |
| `--setup CALL` | A `[model] setup` call, e.g. `'psychrolib:SetUnitSystem(psychrolib.SI)'` or `reset`; run before the probe with `--probe`. Repeatable. |
| `--kind function` | Treat a class whose constructor does the work as a function called every step. |
| `--create CLASSMETHOD` | Build the object with this classmethod (e.g. `from_pretrained`) instead of the class. |
| `--probe` | Also call the model once, to find what reading the code can't (array sizes, runtime results, `save_state`). Without it, the model is never called. |
| `--convert NAME=module:function` | How an argument is passed in, e.g. `x=torch:tensor`. Repeatable. |
| `--force` | Overwrite an existing config. |

What it infers: [models.md](models.md#what-fmugen-init-infers).

### `fmugen build`

```
fmugen build MODEL -o OUTPUT [options]
```

| Argument | Description |
|---|---|
| `MODEL` | A `fmugen.toml`, a directory containing one, or a model (`model.py[:Name]`, `package.module:Name`) whose config is inferred in memory. |
| `-o, --output` | Output path, used exactly as given. |
| `--fmi {2,3}` | FMI version to build. Default: `[model] fmi_version`, else 2. |
| `--format {fmu,folder}` | `fmu` (default): zipped `.fmu` archive. `folder`: unzipped UniFMU folder. |
| `--name` | `modelName` in `modelDescription.xml`; overrides `[model] name`. |
| `--author` | `author` in `modelDescription.xml`; overrides `[model] author`. |
| `--call` | Like `init --call`, when `MODEL` is a `.py` file with a class. |
| `--vendor` | Put wheels of every requirement into the FMU; it installs them offline on its first run. See [FMUs for other machines](#fmus-for-other-machines). |
| `--platform TAG` | With `--vendor`: also vendor wheels for this platform. Repeatable. |
| `--python-version X.Y` | With `--vendor`: vendor wheels for this Python version. Repeatable. |
| `--compile {pyinstaller,nuitka}` | Freeze everything into an executable: no sources in the FMU, no Python needed, this OS only. |
| `--capture-output` | Send what the model prints to the importer's log instead of the console (UniFMU 0.14 hangs when the FMU's Python prints more than about 4 KB). |

---

## What `fmugen build` does

1. Reads and validates `fmugen.toml`, or infers it from a `.py` model.
2. Runs `unifmu generate python <tmp> fmi2` (or `fmi3`) to get the UniFMU boilerplate for the FMI version. Replaces `resources/model.py` with fmugen's adapter for that version (`src/fmugen/templates/model_fmi2.py` or `model_fmi3.py`), and adds the shared engine `resources/fmugen_runtime.py`.
3. Copies the entry file and `sources` into `resources/fmugen_model/`, keeping their paths. Writes `resources/requirements.txt`: the backend's packages and `[model] requirements`.
4. Imports the entry from the copied files, checks the config against it (argument names, function vs class), and writes `resources/interface.json`.
5. Writes `modelDescription.xml` and `launch.toml`, then zips the result (or copies the folder).

`build` imports the model but **never runs it**: no object is constructed, no setup call or step is made. Models that need hardware (TCLab), a network or a licence server build anywhere. `canGetAndSetFMUState` comes from `[model] save_state`, which `fmugen init --probe` sets. `fmugen build model.py`, without a `fmugen.toml`, infers the config like `init`: from the code, without calling the model, unless you pass `build --probe`.

---

## Generated FMU layout

```
model.fmu
├── binaries/                            # UniFMU native libraries (from `unifmu generate`)
├── modelDescription.xml                 # generated from fmugen.toml
└── resources/
    ├── main.py, backend.py, ...         # UniFMU Python backend (from `unifmu generate`)
    ├── schemas/                         # UniFMU protobuf messages
    ├── launch.toml                      # how UniFMU starts the backend per OS
    ├── requirements.txt                 # backend requirements + [model] requirements (a record)
    ├── model.py                         # fmugen's FMI 2 or FMI 3 adapter
    ├── fmugen_runtime.py                # fmugen's engine, shared by both adapters
    ├── interface.json                   # variables, value references, bindings
    ├── fmugen_model/                    # your files, unchanged
    │   └── ...
    └── fmugen_launch.py, wheels/        # only with --vendor
```

With `--compile`, `resources/` holds only `launch.toml` and `dist/main/`, the frozen executable that contains all of the above.

Your code is never rewritten.

`interface.json` is fmugen's normalised description of the model: the FMI version, the entry, `sys.path`, constants, time arguments, the experiment, type definitions, every variable with its binding, and the clocks and events. The engine reads it at runtime, and `modelDescription.xml` is generated from it.

---

## The FMU's Python environment

fmugen is installed in the model's virtual environment, and the FMU runs with that environment's Python. `launch.toml`, which UniFMU uses to start the backend, gets the interpreter running fmugen for the current OS:

```toml
linux = ["python3", "main.py"]
macos = ["python3", "main.py"]
windows = ["C:\\path\\to\\model\\.venv\\Scripts\\python.exe", "main.py"]
```

That environment has everything the FMU needs:

- your model's packages, because you developed the model there
- `protobuf==5.27.3` and `pyzmq`, the UniFMU backend's packages, installed as fmugen's dependencies

The FMU therefore runs on the machine where it was built, as long as that environment exists and keeps those packages. `resources/requirements.txt` records what it must contain: the backend's packages and `[model] requirements`.

---

## FMUs for other machines

An FMU built by default points at your virtual environment, so it doesn't run anywhere else. Two options make FMUs to hand to someone else:

| | `--vendor` | `--compile pyinstaller` / `--compile nuitka` |
|---|---|---|
| **The target needs** | a Python interpreter (`python3` on Linux and macOS, `python` on Windows) | nothing |
| **Source code in the FMU** | yes, readable | no |
| **Runs on** | every platform and Python version whose wheels were vendored | only the OS (and CPU architecture) it was built on |
| **First run on a machine** | installs the wheels into a cached environment, offline | starts immediately |
| **Size** | the wheels | the interpreter and every package, typically 20–100 MB |

### `--vendor`

`fmugen build --vendor` puts wheels of the backend's packages and `[model] requirements`, with their dependencies, into `resources/wheels/`. `launch.toml` then runs `fmugen_launch.py` with the system Python:

```toml
linux = ["python3", "fmugen_launch.py"]
macos = ["python3", "fmugen_launch.py"]
windows = ["python", "fmugen_launch.py"]
```

On the FMU's first run on a machine, `fmugen_launch.py` creates a virtual environment, installs the wheels into it without a network connection (`--no-index`), and caches it. Then it starts UniFMU's `main.py` with that environment. Later runs, and other FMUs with the same wheels, reuse it. The cache is in `FMUGEN_ENV_DIR` if set, else `%LOCALAPPDATA%\fmugen\envs` (Windows), `~/Library/Caches/fmugen/envs` (macOS) or `~/.cache/fmugen/envs` (Linux). FMU instances starting at the same time are safe.

`[model] requirements` must list every package the model needs from PyPI: only those are vendored, not everything in your environment.

By default, wheels are made for this machine and Python (`pip wheel`; packages published only as source are built here). For other targets, list them. Only published wheels can be used for those:

```bash
fmugen build examples/simple_pid -o out/pid.fmu --vendor --platform win_amd64 --platform manylinux2014_x86_64 --platform macosx_11_0_arm64 --python-version 3.11 --python-version 3.12 --python-version 3.13
```

Vendoring uses the environment's `pip`, or `uvx pip` when the environment has none (uv venvs).

### `--compile`

`fmugen build --compile pyinstaller` (or `nuitka`) freezes UniFMU's backend, fmugen's adapter and runtime, your model and every package it imports, together with the Python interpreter, into `resources/dist/main/`. All `.py` files, `fmugen_model/`, `interface.json` and `requirements.txt` are removed from the FMU; `resources/` keeps only `dist/` and `launch.toml`:

```toml
linux = ["sh", "-c", "chmod +x dist/main/main && ./dist/main/main"]
macos = ["sh", "-c", "chmod +x dist/main/main && ./dist/main/main"]
windows = ["powershell", "-command", "./dist/main/main.exe"]
```

Install the compiler in your environment first: `pip install fmugen[pyinstaller]` or `pip install fmugen[nuitka]`.

| | PyInstaller | Nuitka |
|---|---|---|
| **How the code ships** | Python bytecode inside the bundle | compiled to C, then machine code |
| **Hiding the source** | light: bytecode can be decompiled to readable Python | strong: as hard to reverse as other compiled FMUs |
| **Build time** | about a minute | several minutes or more; needs a C compiler (on Windows, Nuitka downloads one) |

Neither can cross-compile: the executable runs only on the OS and CPU architecture of the machine that built it. To ship for several OSes, build on each one.

fmugen tells the compiler about the modules the runtime imports by name (the model's entry, `setup` calls, enums, references in constants, clock calls) and bundles the model's non-Python files next to its modules. A package that imports parts of itself dynamically may still be missed; the build's error, or the FMU's log, then names the missing module.

---

## Simulating

```bash
fmpy simulate out/psychrometry.fmu --stop-time 10 --start-values temp_1 30 --output-file out/results.csv
```

FMPy simulates FMI 2 and FMI 3 FMUs the same way. In Python, `fmpy.simulate_fmu(..., event_mode_used=True)` also handles output clocks (`eventHandlingNeeded`) and `[events] terminate`. FMPy never ticks *input* clocks, though. FMUs whose code runs on input clocks need an importer that ticks them, or a script using `fmpy.fmi3.FMU3Slave` (see `tests/test_fmi3.py`).

Time-varying inputs come from a CSV whose first column is time. Here they come from the RC building example's weather file (build the FMU first, as in [examples/rc_building](../examples/rc_building/README.md)):

```bash
fmpy simulate out/rc_building.fmu --input-file examples/rc_building/weather.csv --output-interval 3600 --output-file out/rc_building.csv
```

Without `--output-file`, FMPy plots the result instead, which requires matplotlib (`pip install matplotlib`).

```bash
uv run python -m fmpy.gui
```

In the GUI, open the `.fmu`, set start values, press play, and tick outputs to plot.

![FMPy GUI example](../image.png)

---

## Project layout

| Path | Contents |
|---|---|
| `src/fmugen/config.py` | `fmugen.toml` loading, validation, normalisation into the interface spec (FMI 2 and 3) |
| `src/fmugen/interface.py` | `fmugen init`: inference and TOML output |
| `src/fmugen/description.py` | `modelDescription.xml` writers (FMI 2 and FMI 3) |
| `src/fmugen/templates/fmugen_runtime.py` | The engine copied into every FMU: runs the user's code, values, clocks, state |
| `src/fmugen/templates/model_fmi2.py`, `model_fmi3.py` | The adapters copied into the FMU as `resources/model.py`: FMI calls → engine |
| `src/fmugen/__main__.py` | CLI, packaging, UniFMU version check |
| `src/fmugen/distribute.py` | `--vendor` and `--compile` |
| `src/fmugen/templates/fmugen_launch.py` | The launcher of vendored FMUs: offline install into a cached environment |
| `examples/` | Example models with their `fmugen.toml` |
| `tests/` | `uv run pytest` |
| `docker/` | FMU + OPC UA + Streamlit demo stack (see [docker/Readme.md](../docker/Readme.md)) |

---

## UniFMU version

fmugen doesn't ship UniFMU. Every `fmugen build` runs the UniFMU CLI to generate the FMU skeleton (native binaries for Windows, Linux and macOS, plus the Python backend), so it must be installed:

- Download UniFMU **0.14.0** from https://github.com/INTO-CPS-Association/unifmu/releases.
- Put `unifmu` on `PATH`, or set `FMUGEN_UNIFMU` to the executable's path.

fmugen runs `unifmu --version` and refuses any other version, because the adapters (`resources/model.py`) are written against that version's `backend.py` and protobuf messages. The pinned version is `UNIFMU_VERSION` in `src/fmugen/__main__.py`.

UniFMU 0.14 writes `fmiVersion="3.0-beta.4"` into the FMI 3 template's `modelDescription.xml`. That file is replaced on every build, so it doesn't matter.

`fmugen` replaces `resources/model.py` and `modelDescription.xml`, adds `fmugen_runtime.py`, `interface.json` and `fmugen_model/`, and rewrites `requirements.txt` and `launch.toml`. The backend and binaries are taken as-is.

To move to a newer UniFMU: change `UNIFMU_VERSION`, check the backend's command list in the generated `resources/backend.py` against [fmi.md](fmi.md) and the adapters, then run `uv run pytest`. If the new backend imports other packages, update `BACKEND_REQUIREMENTS` and fmugen's dependencies in `pyproject.toml`.
