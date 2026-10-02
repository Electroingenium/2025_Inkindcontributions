# fmugen: Python models → UniFMU FMUs

`fmugen` turns an ordinary Python model into a [UniFMU](https://github.com/INTO-CPS-Association/unifmu) FMU (FMI 2.0 or FMI 3.0 Co-Simulation) that any FMI importer can run.

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
| Matrices and vectors (lists, numpy), sized by constructor arguments | FMI 3 arrays and structural parameters | [`examples/kalman`](examples/kalman) |
| A method that should run on events, not every step | FMI 3 clocks: periodic, triggered, or raised by the model | [`examples/sampled_pid`](examples/sampled_pid), [`examples/kalman`](examples/kalman) |

## FMI 2 and FMI 3

FMUs are FMI 2.0 by default. Set `[model] fmi_version = 3` in `fmugen.toml`, or pass `--fmi 3` to `fmugen build`, for FMI 3.0. A config that doesn't use FMI 3-only features builds either version; the three FMI 2 examples give the same results as FMI 3.

Both versions support what UniFMU's Python backend supports for Co-Simulation:
- parameters (fixed and tunable) and calculated parameters
- inputs, outputs, locals and states
- variable or fixed step size, and a default experiment
- saving and restoring FMU state, which lets an importer roll back
- reset
- log messages from the model's `logging` calls, forwarded to the importer

FMI 2 has Real, Integer, Boolean, String and Enumeration variables. FMI 3 adds:
- Float32, Int8…UInt64 and Binary variables
- arrays, with sizes set by structural parameters (configuration mode)
- clocks, including periodic and triggered input clocks, output clocks raised by the model, and their intervals and shifts
- event mode, and letting the model stop the simulation

See [docs/fmi.md](docs/fmi.md) for what each FMI call does, function by function for both versions, and what isn't supported.

---

## Documentation

| Page | Contents |
|---|---|
| [docs/models.md](docs/models.md) | Writing models: the supported shapes with examples, what `fmugen init` infers and what to check |
| [docs/config.md](docs/config.md) | `fmugen.toml` reference: every key and its default |
| [docs/fmi.md](docs/fmi.md) | FMI 2 and FMI 3 behaviour: function-by-function support, initialization, steps, clocks, state, logging |
| [docs/packaging.md](docs/packaging.md) | CLI, the generated FMU's layout, requirements and `--vendor`, the runtime Python, updating UniFMU |
| [docker/Readme.md](docker/Readme.md) | Demo stack: the FMU in Docker, exchanging data over OPC UA, with a Streamlit dashboard |

---

## CLI

```
uv run fmugen init MODEL [-o fmugen.toml] [--call METHOD] [--fmi {2,3}] [--force]
uv run fmugen build MODEL -o OUTPUT [--fmi {2,3}] [--format fmu|folder] [--python [PATH]] [--vendor] [--name NAME] [--author AUTHOR]
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
- **Adapter:** the generated adapters' behaviour for every FMI 2 and FMI 3 call, including clocks, arrays and configuration mode.
- **Inference:** `fmugen init` on the examples and on small models.
- **FMU validity:** `modelDescription.xml` is checked with FMPy's validator.
- **Real runs:** simulations through UniFMU for both versions. These cover every supported FMI 3 type, clocks, intervals and shifts, state save/restore, and changing a tunable parameter.

---

## References

- UniFMU: https://github.com/INTO-CPS-Association/unifmu
- FMI 2.0 standard: https://fmi-standard.org/
- FMPy: https://github.com/CATIA-Systems/FMPy
- Legaard, C. M., Tola, D., Schranz, T., Macedo, H. D., & Larsen, P. G. (2021). *A Universal Mechanism for Implementing Functional Mock-up Units*. SIMULTECH 2021, pp. 121–129. https://doi.org/10.5220/0010577601210129

## Credits

- Original psychrometry model and UniFMU workflow by Lucia Royo-Pascual, Ph.D. (EIUM).
- Example models from [simple-pid](https://github.com/m-lundberg/simple-pid) (MIT, Martin Lundberg), [RC_BuildingSimulator](https://github.com/architecture-building-systems/RC_BuildingSimulator) (MIT, Architecture and Building Systems, ETH Zürich) and [FilterPy](https://github.com/rlabbe/filterpy) (MIT, Roger R. Labbe). See each example's README.
