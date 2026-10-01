# Python model → UniFMU generator

Turns a plain Python model into a [UniFMU](https://github.com/INTO-CPS-Association/unifmu) FMU (FMI 2.0 Co-Simulation).

You write a Python module that declares its inputs and outputs and has a `step()` function. `fmugen` reads that interface from the module and generates everything else (`modelDescription.xml`, the UniFMU adapter, packaging). Your model file is copied into the FMU unchanged, and no model logic is generated or duplicated.

The example model is [`src/fmu_psycrometry.py`](src/fmu_psycrometry.py), a simplified mass and energy balance of an air-based drying process.

---

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.13 and the dependencies from `pyproject.toml`)

```bash
uv sync
```

---

## Quick start

Build the example model into an FMU:

```bash
uv run python src/update_and_package_fmu.py build src/fmu_psycrometry.py -o out/psycrometry.fmu --python
```

Check it:

```bash
uv run fmpy validate out/psycrometry.fmu
```

```bash
uv run fmpy simulate out/psycrometry.fmu --stop-time 5 --output-file out/psycrometry.csv
```

---

## Writing a model

A model is a Python module with three things:

```python
INPUTS = {
    "temp_1": {"start": 28.0, "unit": "degC"},
    "vfr_5":  {"start": 1.2,  "unit": "m3/s"},
}

OUTPUTS = {
    "mdot_air_in": {"unit": "kg/s"},
}

def step(temp_1, vfr_5):
    return {"mdot_air_in": vfr_5 * 1.2}
```

| Name | Required | Description |
|---|---|---|
| `INPUTS` | yes | `{name: info}` of FMU inputs. |
| `OUTPUTS` | yes | `{name: info}` of FMU outputs. |
| `PARAMETERS` | no | Same shape as `INPUTS`; becomes `causality="parameter"`, settable before initialization. |
| `step(**inputs)` | yes | Called with every input and parameter as a keyword argument. Must return a dict containing every output. |

Each `info` dict is optional (`{}` or `None` is fine) and accepts:

| Key | Default | Notes |
|---|---|---|
| `start` | `0.0` / `0` / `False` / `""` | Value used until the importer sets the variable. Not used for outputs. |
| `type` | inferred from `start`, else `Real` | `Real`, `Integer`, `Boolean` or `String`. Needed for non-Real variables without a `start`. |
| `unit` | none | Informational only; written to `modelDescription.xml`. |
| `description` | none | Written to `modelDescription.xml`. |

Notes:

- `step()` is stateless: it is called on initialization and on every `doStep` with the current inputs.
- Variable names must be valid Python identifiers and match the `step()` parameter names.
- At build time `step()` is called once with the start values to check that all outputs are returned. If an input of `0.0` would break your model (e.g. a division), give it a non-zero `start`.
- The module docstring becomes the FMU description.
- Anything the model imports must be installed in the Python that runs the FMU (see [Runtime Python](#runtime-python)).

---

## CLI

```
python src/update_and_package_fmu.py build MODEL -o OUTPUT [options]
```

Equivalent: `python -m fmugen build ...` from inside `src/`.

| Option | Description |
|---|---|
| `-o, --output` | Output path, used exactly as given. |
| `--format {fmu,folder}` | `fmu` (default): zipped `.fmu` archive. `folder`: unzipped UniFMU folder. |
| `--python [PATH]` | Python executable written into `launch.toml` for Windows. The flag alone uses the current interpreter. If omitted, the boilerplate's `python` is kept. |
| `--name` | `modelName` in `modelDescription.xml` (default: the module name). |
| `--author` | `author` in `modelDescription.xml`. |

---

## How it works

```
model.py (INPUTS / OUTPUTS / step)
   │  fmugen imports it and reads the interface
   ▼
interface spec ──► modelDescription.xml
               └─► resources/interface.json
   +  src/fmu/ boilerplate (binaries, UniFMU backend)
   +  generic resources/model.py adapter (same for every model)
   +  your model file, copied as-is
   ▼
.fmu archive or folder
```

Generated FMU layout:

```
psycrometry.fmu
├── binaries/{win64,linux64,darwin64}/   # UniFMU native libraries
├── modelDescription.xml                 # generated from the interface
└── resources/
    ├── main.py, backend.py, ...         # UniFMU Python backend (boilerplate)
    ├── launch.toml                      # how UniFMU starts the backend per OS
    ├── model.py                         # generic adapter: loads interface.json, calls step()
    ├── interface.json                   # variables, value references, start values
    └── fmu_psycrometry.py               # your model, unchanged
```

### Project layout

| Path | Contents |
|---|---|
| `src/fmugen/` | The generator: `interface.py` (introspection), `description.py` (XML), `templates/model.py` (adapter), `__main__.py` (CLI). |
| `src/fmu/` | UniFMU Python boilerplate the FMU is built from. |
| `src/fmu_psycrometry.py` | Example model. |
| `src/update_and_package_fmu.py` | Entry point for the `fmugen` CLI. |
| `src/simulate_fmu.py` | Runs an FMU with FMPy and writes a CSV and PDF of inputs and outputs. |
| `tools/unifmu.exe` | UniFMU CLI, used to regenerate `src/fmu/`. |
| `docker/` | FMU + OPC UA + Streamlit demo stack (see [docker/Readme.md](docker/Readme.md)). |

### Updating the UniFMU boilerplate

`src/fmu/` was created with the UniFMU CLI. To refresh it with a newer UniFMU version:

```bash
./tools/unifmu.exe generate python src/fmu fmi2
```

`fmugen` only replaces `resources/model.py`, `modelDescription.xml` and (with `--python`) `launch.toml`, so the backend and binaries are taken as-is from this folder.

---

## Runtime Python

UniFMU starts the model in a separate Python process using the command in `resources/launch.toml`. That Python needs:

- `protobuf==5.27.3`, `pyzmq` (UniFMU backend; see `resources/requirements.txt`)
- everything your model imports

Options:

- `--python` writes the current interpreter (e.g. the project's `.venv`) into `launch.toml`. Simplest for local use, but the FMU only works on that machine.
- Without it, the FMU uses `python` / `python3` from `PATH`, which must have the packages above installed.

---

## Simulating

**FMPy CLI or GUI**

```bash
uv run fmpy simulate out/psycrometry.fmu --stop-time 10 --start-values temp_1 30 --output-file out/results.csv
```

Without `--output-file`, FMPy plots the result instead, which requires matplotlib (`uv run --with matplotlib ...`).

```bash
uv run python -m fmpy.gui
```

In the GUI, open the `.fmu`, set start values, press play, and tick outputs to plot.

![FMPy GUI example](image.png)

**`simulate_fmu.py`**

Runs the FMU from t=0 to 10 s and writes `results/simulation_inputs_outputs.csv` and `results/simulation_plots.pdf` in the current directory. Output names are read from the FMU. It needs pandas and matplotlib, which are not project dependencies:

```bash
uv run --with pandas --with matplotlib python src/simulate_fmu.py out/psycrometry.fmu
```

On Windows consoles, set `PYTHONIOENCODING=utf-8` first, as the script prints emoji.

---

## References

- UniFMU: https://github.com/INTO-CPS-Association/unifmu
- FMPy: https://github.com/CATIA-Systems/FMPy
- Legaard, C. M., Tola, D., Schranz, T., Macedo, H. D., & Larsen, P. G. (2021). *A Universal Mechanism for Implementing Functional Mock-up Units*. SIMULTECH 2021, pp. 121–129. https://doi.org/10.5220/0010577601210129

## Credits

Original psychrometry model and UniFMU workflow by Lucia Royo-Pascual, Ph.D. (EIUM).
