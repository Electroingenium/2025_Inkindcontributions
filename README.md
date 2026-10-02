# fmugen: Python models → UniFMU FMUs

`fmugen` turns an ordinary Python model into a [UniFMU](https://github.com/INTO-CPS-Association/unifmu) FMU (FMI 2.0 Co-Simulation) that any FMI importer can run.

**You don't change your code.** A plain function, a class with a step method, a multi-file package, or a model from PyPI is packaged as it is. What fmugen needs to know (which function or class to call, which arguments are inputs or parameters, where outputs come from, units) lives in a separate `fmugen.toml`. `fmugen init` writes a first version of that file by inspecting your model.

---

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.13, the dependencies from `pyproject.toml`, and the `fmugen` command:

```bash
uv sync
```

---

## Quick start

For your own model:

1. Let fmugen inspect the model and write `fmugen.toml` next to it:

   ```bash
   uv run fmugen init path/to/your_model.py
   ```

2. Review the file. Check the start values, add units, and remove anything you don't want in the FMU.
3. Build:

   ```bash
   uv run fmugen build path/to/fmugen.toml -o out/your_model.fmu --python
   ```

The examples already have reviewed configs. To see what `init` would infer for one without overwriting it, print to the terminal:

```bash
uv run fmugen init examples/psychrometry/psychrometry.py -o -
```

Then build it, validate it, and simulate it:

```bash
uv run fmugen build examples/psychrometry -o out/psychrometry.fmu --python
```

```bash
uv run fmpy validate out/psychrometry.fmu
```

```bash
uv run fmpy simulate out/psychrometry.fmu --stop-time 5 --output-file out/psychrometry.csv
```

For a quick try you can skip the config and build straight from a `.py` file. fmugen then infers the config in memory, without units:

```bash
uv run fmugen build examples/psychrometry/psychrometry.py -o out/quick.fmu --python
```

---

## What a model can look like

| Your code | How it runs in the FMU | Example |
|---|---|---|
| A function `f(a, b, ...)` returning a dict, tuple, number or object | Called once per step; outputs are read from the return value | [`examples/psychrometry`](examples/psychrometry) |
| A class `C(params...)` with a method `step(inputs...)` / `__call__` | Built once at initialization; the method is called once per step | [`examples/simple_pid`](examples/simple_pid) |
| A method that stores its results as attributes | Outputs are read from the object's attributes after each step | [`examples/rc_building`](examples/rc_building) |
| A method that needs last step's value (`x_prev`) | A *state*: fed back from the result after each step | [`examples/rc_building`](examples/rc_building) |
| Code that needs the time or step size (`t`, `dt`) | The FMU passes its communication time / step size | [`examples/simple_pid`](examples/simple_pid) |
| Several files, flat or package imports | Copied into the FMU with their layout | [`examples/rc_building`](examples/rc_building) |
| A package from PyPI | Listed as a requirement, optionally vendored into the FMU | [`examples/simple_pid`](examples/simple_pid) |

The FMU supports FMI 2 Co-Simulation as far as UniFMU's Python backend goes:
- parameters (fixed and tunable) and calculated parameters
- inputs, outputs, locals and states
- Real, Integer, Boolean, String and Enumeration variables
- variable or fixed step size, and a default experiment
- saving and restoring FMU state, which lets an importer roll back
- reset
- log messages from the model's `logging` calls, forwarded to the importer

See [docs/fmi.md](docs/fmi.md) for what each FMI call does and what isn't supported.

---

## Documentation

| Page | Contents |
|---|---|
| [docs/models.md](docs/models.md) | Writing models: the supported shapes with examples, what `fmugen init` infers and what to check |
| [docs/config.md](docs/config.md) | `fmugen.toml` reference: every key and its default |
| [docs/fmi.md](docs/fmi.md) | FMI 2 behaviour: initialization, steps, parameters, state, logging, unsupported functions |
| [docs/packaging.md](docs/packaging.md) | CLI, the generated FMU's layout, requirements and `--vendor`, the runtime Python, updating UniFMU |
| [docker/Readme.md](docker/Readme.md) | Demo stack: the FMU in Docker, exchanging data over OPC UA, with a Streamlit dashboard |

---

## CLI

```
uv run fmugen init MODEL [-o fmugen.toml] [--call METHOD] [--force]
uv run fmugen build MODEL -o OUTPUT [--format fmu|folder] [--python [PATH]] [--vendor] [--name NAME] [--author AUTHOR]
```

`MODEL` can be any of these:
- for `build`: a `fmugen.toml`, or a directory containing one
- for both: `model.py`, `model.py:Name`, or `package.module:Name` for an installed module

Details are in [docs/packaging.md](docs/packaging.md#cli).

---

## Tests

```bash
uv run pytest
```

The tests cover:
- **Adapter:** the generated adapter's behaviour for every FMI call.
- **Inference:** `fmugen init` on the examples and on small models.
- **FMU validity:** `modelDescription.xml` is checked with FMPy's validator.
- **Real runs:** simulations through UniFMU, including state save/restore and changing a tunable parameter.

---

## References

- UniFMU: https://github.com/INTO-CPS-Association/unifmu
- FMI 2.0 standard: https://fmi-standard.org/
- FMPy: https://github.com/CATIA-Systems/FMPy
- Legaard, C. M., Tola, D., Schranz, T., Macedo, H. D., & Larsen, P. G. (2021). *A Universal Mechanism for Implementing Functional Mock-up Units*. SIMULTECH 2021, pp. 121–129. https://doi.org/10.5220/0010577601210129

## Credits

- Original psychrometry model and UniFMU workflow by Lucia Royo-Pascual, Ph.D. (EIUM).
- Example models from [simple-pid](https://github.com/m-lundberg/simple-pid) (MIT, Martin Lundberg) and [RC_BuildingSimulator](https://github.com/architecture-building-systems/RC_BuildingSimulator) (MIT, Architecture and Building Systems, ETH Zürich). See each example's README.
