# Packaging and runtime

- [CLI](#cli)
- [What `fmugen build` does](#what-fmugen-build-does)
- [Generated FMU layout](#generated-fmu-layout)
- [The FMU's Python environment](#the-fmus-python-environment)
- [Simulating](#simulating)
- [Project layout](#project-layout)
- [UniFMU version](#unifmu-version)

---

## CLI

Install fmugen into your model's virtual environment (`pip install fmugen`) and run it from there. `fmugen build` also needs the UniFMU 0.14.0 CLI (see [UniFMU version](#unifmu-version)). To work on fmugen itself, `uv sync` installs it in editable mode with the test dependencies.

### `fmugen init`

```
fmugen init MODEL [-o OUTPUT] [--call METHOD] [--fmi {2,3}] [--start NAME=VALUE ...] [--setup CALL ...] [--kind function] [--force]
```

| Argument | Description |
|---|---|
| `MODEL` | `model.py`, `model.py:Name`, or `package.module:Name` (an installed module). |
| `-o, --output` | Where to write the config. Default: `fmugen.toml` next to the model (or in the current directory for an installed module). `-` prints it instead. The model file must be inside the config's folder. |
| `--call` | For classes: the method run on each step, when it isn't `step`/`do_step`/`update`/`__call__`/the only public method. |
| `--fmi {2,3}` | Write `fmi_version` into the config. With `3`, also infer arrays and Binary. |
| `--start NAME=VALUE` | Start and probe value for an argument (a Python literal), e.g. one without a default. Repeatable. |
| `--setup CALL` | A `[model] setup` call to run before the probe, e.g. `'psychrolib:SetUnitSystem(psychrolib.SI)'` or `reset`. Repeatable. |
| `--kind function` | Treat a class whose constructor does the work as a function called every step. |
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

---

## What `fmugen build` does

1. Reads and validates `fmugen.toml`, or infers it from a `.py` model.
2. Runs `unifmu generate python <tmp> fmi2` (or `fmi3`) to get the UniFMU boilerplate for the FMI version. Replaces `resources/model.py` with fmugen's adapter for that version (`src/fmugen/templates/model_fmi2.py` or `model_fmi3.py`), and adds the shared engine `resources/fmugen_runtime.py`.
3. Copies the entry file and `sources` into `resources/fmugen_model/`, keeping their paths. Writes `resources/requirements.txt`: the backend's packages and `[model] requirements`.
4. Imports the entry from the copied files, checks the config against it (argument names, function vs class), and writes `resources/interface.json`.
5. **Probe:** runs the packaged model once through the real adapter: setup, initialization, one tick of every input clock (FMI 3), one `doStep`, then save and restore state. A model that fails here fails the build, with the model's error message. Whether the state could be saved decides `canGetAndSetFMUstate`.
6. Writes `modelDescription.xml` and `launch.toml`, then zips the result (or copies the folder).

The probe runs the model in the Python running fmugen, the same one the FMU will use.

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
```

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
| `src/fmugen/__main__.py` | CLI, packaging, build probe, UniFMU version check |
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
