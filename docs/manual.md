# fmugen manual

The complete reference for the `fmugen` command and the `fmugen.toml` config, on one page. For explanations with worked examples, see [models.md](models.md). For runtime FMI behaviour, see [fmi.md](fmi.md).

**Contents**

1. [Overview](#1-overview)
2. [Installation](#2-installation)
3. [Workflow](#3-workflow)
4. [Commands](#4-commands)
   - [`fmugen init`](#fmugen-init)
   - [`fmugen build`](#fmugen-build)
   - [Model targets](#model-targets)
   - [Errors and exit codes](#errors-and-exit-codes)
5. [Configuration: `fmugen.toml`](#5-configuration-fmugentoml)
   - [File layout](#file-layout)
   - [`[model]`](#model)
   - [`[model.constants]`, `[model.call_constants]`](#modelconstants-modelcall_constants)
   - [`[experiment]`](#experiment)
   - [`[time]`](#time)
   - [Variable sections](#variable-sections)
   - [Variable keys](#variable-keys)
   - [Bindings: `to`, `from`, `next`](#bindings-to-from-next)
   - [Types](#types)
   - [`[clocks.<name>]`](#clocksname)
   - [`[events]`](#events)
   - [Value syntax](#value-syntax)
   - [Validation rules](#validation-rules)
6. [Complete example](#6-complete-example)
7. [Recipes](#7-recipes)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Overview

`fmugen` turns an unmodified Python model into a [UniFMU](https://github.com/INTO-CPS-Association/unifmu) FMU: FMI 2.0 or FMI 3.0, Co-Simulation.

- **The model** is any importable function or class: your own file or an installed package. It is never edited.
- **`fmugen.toml`** says how the model maps onto FMU variables: which arguments are inputs or parameters, where outputs come from, units, the experiment, and so on.
- **`fmugen init`** writes a first `fmugen.toml` by inspecting the model.
- **`fmugen build`** packages the model and its config into an `.fmu`.

---

## 2. Installation

Install fmugen into your model's virtual environment, the one that already has the model's packages:

```bash
pip install fmugen
```

(or `uv add fmugen`). This also installs `protobuf==5.27.3` and `pyzmq`, which UniFMU's Python backend needs to run the FMU. Run `fmugen` from that environment: `init` and `build` import your model, and the FMU runs with the environment's Python.

You also need [UniFMU](https://github.com/INTO-CPS-Association/unifmu/releases) **0.14.0** (exactly this version) for `fmugen build`. fmugen runs `unifmu generate` to get each FMU's native binaries and Python backend. Put `unifmu` on `PATH`, or set the environment variable `FMUGEN_UNIFMU` to the executable. `fmugen init` works without it.

To simulate and validate FMUs as in the examples below, install [FMPy](https://github.com/CATIA-Systems/FMPy) (`pip install fmpy`).

To work on fmugen itself, clone the repository and run `uv sync`; then use `uv run fmugen …` and `uv run pytest`.

## 3. Workflow

```
your model ──► fmugen init ──► fmugen.toml ──► (review & edit) ──► fmugen build ──► model.fmu
```

1. Infer a config:

   ```bash
   fmugen init path/to/model.py
   ```

2. Review `path/to/fmugen.toml`. Check the start values, add units, and remove what you don't need.
3. Build:

   ```bash
   fmugen build path/to/fmugen.toml -o out/model.fmu
   ```

4. Check the FMU:

   ```bash
   fmpy validate out/model.fmu
   ```

   ```bash
   fmpy simulate out/model.fmu --output-file out/result.csv
   ```

For a quick try, `fmugen build path/to/model.py -o out/model.fmu` skips step 2: the config is inferred in memory.

---

## 4. Commands

```
fmugen init  MODEL [options]
fmugen build MODEL -o OUTPUT [options]
```

### `fmugen init`

Imports the model, reads its signatures and **its source code**, and writes a commented `fmugen.toml`. **The model is not called**: no object is built and no step is run, so models that need a device, a network or a licence can be configured anywhere. Importing the module still runs its top-level code, as any import does. With `--probe`, `init` also calls the model once, to find what the code doesn't show.

```
fmugen init MODEL [-o OUTPUT] [--call METHOD] [--fmi {2,3}]
                  [--start NAME=VALUE ...] [--setup CALL ...] [--kind function] [--create CLASSMETHOD]
                  [--probe] [--convert NAME=module:function ...] [--force]
```

| Option | Default | Description |
|---|---|---|
| `MODEL` | required | A [model target](#model-targets): `model.py`, `model.py:Name` or `package.module:Name`. |
| `-o`, `--output PATH` | `fmugen.toml` next to the model (current directory for an installed module) | Where to write the config; missing folders are created. `-o -` prints it instead. A model file must be inside the config's folder. |
| `--call METHOD` | `step`, `do_step`, `update`, `__call__`, or the only public method | Classes: the method run on each step. |
| `--fmi {2,3}` | none (FMI 2) | Writes `fmi_version` into the config. With `3`, list/tuple/numpy values are inferred as arrays, `bytes` as Binary and numpy `float32` as Float32. |
| `--start NAME=VALUE` | none | Start value (and, with `--probe`, the value it is called with) for an argument; repeatable. `VALUE` is a Python literal (`1e5`, `"Water"`, `[1.0, 0.0]`); a bare word is taken as a string. `true`/`false` are booleans. A tuple or dict value is split into one variable per item. `call:module:function(args)` makes a [computed constant](#value-syntax) instead of a variable (`call:module:attr` without parentheses passes the object itself, e.g. a function). Use it for arguments without a default, or whose default breaks the model. |
| `--setup CALL` | none | A [setup call](#model), written to `[model] setup`; with `--probe` it is also run before the probe. Repeatable. E.g. `"psychrolib:SetUnitSystem(psychrolib.SI)"`, `reset`. |
| `--kind function` | none | Treat a class whose constructor does the work as a function called on every step (writes `[model] kind`). |
| `--create CLASSMETHOD` | none | Classes built by a factory: the classmethod that creates the object, e.g. `from_pretrained`. Its arguments become parameters (writes `[model] create`). |
| `--probe` | off | Also **call the model once**: run the setup calls, build the object, call the step with the start values (retrying array inputs as numpy arrays, then tensors), and try to pickle the object. Finds what the code doesn't show: array sizes, exact types, results built at runtime, unannotated properties, and `save_state`. Results the code shows but the probe didn't reach are added too. Without `--probe`, the model is never called. |
| `--convert NAME=module:function` | none | How an argument is passed to the model, e.g. `x=torch:tensor`, or `x=numpy` for a numpy array; writes `convert` / `numpy`. Repeatable. Not needed when the argument is annotated (`torch.Tensor`, `np.ndarray`). |
| `--force` | off | Overwrite an existing config. |

**Where `--start` values go.** If a name is an argument of both the constructor and the step method, the value goes to the one that has no default; on a tie, to the step method. A name that neither declares goes to whichever accepts `**kwargs`, the step method first. A name that matches nothing is an error.

**What `init` infers:**

| | From |
|---|---|
| Entry | the name after `:`; else the only public function or class defined in the module |
| Inputs (functions) / parameters (classes) | arguments with a `bool`/`int`/`float`/`str` default, without a default, or given `--start` |
| Start values and types | the default or `--start` value; otherwise the annotation; otherwise Real `0.0` |
| Time arguments | arguments named `dt`, `step_size`, `h` (step size) or `t`, `time` (time) |
| Outputs from the return value | read from the code: dict keys (also a dict built in a variable), tuple positions (`y0`, `y1`, …), a single value (`y`), NamedTuple/dataclass fields, or the return annotation. An argument returned as it is keeps its type (e.g. an enum) |
| Class outputs and locals | public attributes the step method assigns, following the methods it calls on `self`: also assigned in `__init__` → local, else output. Properties of the model's own classes with a type annotation → outputs; without one → a commented line (reading a property runs code) |
| Types of outputs | annotations; booleans from comparisons and `True`/`False`; strings; otherwise Real. Lists, arrays and objects are never written as scalars |
| States | an input `x_prev` whose next value is returned or stored as `x_next` or `x` |
| Sources | local modules under the config's folder that the model imported |
| Positional-only arguments | bound with `to = "pos:N"` |
| Constants | non-FMI defaults (`None`, tuples, objects), written as commented-out examples |

**Not inferred from the code** (use `--probe`, or write them by hand; the config says so in comments):

- **Array sizes.** With `--fmi 3`, array results appear as commented lines with `dimensions = [...]` to fill in. With FMI 2, arrays can't be FMU variables, so they're left out.
- **Results built at runtime** (filled in loops, set by helper functions, returned from library calls) and **code without Python source** (C extensions, compiled models): the `[outputs]` section says the outputs couldn't be read.
- **Unannotated properties**: commented lines, to uncomment if they are numbers.
- **`save_state`** (whether the object can be pickled): a commented `save_state = false` line to uncomment if the model holds a device, file, socket or ONNX session.
- **Factories without a return annotation**: the step method's inputs and outputs, because the object's class is only known by calling the factory.

**Never inferred:** units, descriptions, tunable variability (suggested in comments), states with other names, clocks, events, setter-method inputs (`call:`). With `--probe`, if the probe call fails, `init` still writes the config, with what the code shows, and says why in a comment.

**Examples:**

```bash
fmugen init examples/psychrometry/psychrometry.py -o -
```

```bash
fmugen init simple_pid:PID -o pid/fmugen.toml
```

```bash
fmugen init fluids.friction:friction_factor --start Re=1e5 -o -
```

```bash
fmugen init psychrolib:GetHumRatioFromRelHum --setup "psychrolib:SetUnitSystem(psychrolib.SI)" --start TDryBulb=25.0 --start RelHum=0.5 --start Pressure=101325.0 -o -
```

```bash
fmugen init filterpy.kalman:KalmanFilter --call predict --fmi 3 --start dim_x=2 --start dim_z=1 -o -
```

### `fmugen build`

Packages the model into an FMU. Before writing the FMU, it runs the packaged model once through the real adapter: initialization, one tick of each input clock (FMI 3), one step, and saving and restoring state. A model that fails there fails the build with the model's own error.

```
fmugen build MODEL -o OUTPUT [--fmi {2,3}] [--format {fmu,folder}]
                   [--name NAME] [--author AUTHOR] [--call METHOD]
                   [--vendor [--platform TAG ...] [--python-version X.Y ...] | --compile {pyinstaller,nuitka}]
                   [--capture-output] [--hf-weights | --no-hf-weights]
```

| Option | Default | Description |
|---|---|---|
| `MODEL` | required | A `fmugen.toml`, a directory containing one, or a [model target](#model-targets). For a model target, the config is inferred in memory, as `init` would without options. |
| `-o`, `--output PATH` | required | Output path, used exactly as given. Parent directories are created. |
| `--fmi {2,3}` | `[model] fmi_version`, else `2` | FMI version to build. |
| `--format {fmu,folder}` | `fmu` | `fmu`: zipped `.fmu` archive. `folder`: unzipped UniFMU folder. |
| `--name NAME` | `[model] name`, else the entry's name | `modelName` in `modelDescription.xml`. |
| `--author AUTHOR` | `[model] author`, else empty | `author` in `modelDescription.xml`. |
| `--call METHOD` | as `init` | Only when `MODEL` is a model target with a class. |
| `--vendor` | off | Put wheels of every requirement (`[model] requirements` and the backend's) into `resources/wheels/`. On its first run on a machine, the FMU installs them into a cached virtual environment, offline. The target needs Python. See [packaging.md](packaging.md#fmus-for-other-machines). |
| `--platform TAG` | this machine | With `--vendor`: also vendor wheels for this platform, e.g. `win_amd64`, `manylinux2014_x86_64`, `macosx_11_0_arm64`. Repeatable. |
| `--python-version X.Y` | this Python | With `--vendor`: vendor wheels for this Python version. Repeatable. |
| `--compile {pyinstaller,nuitka}` | off | Freeze the model, its packages and Python into an executable (`resources/dist/main/`). The FMU contains no source code and needs no Python, but only runs on the OS it was built on. Needs `pip install fmugen[pyinstaller]` or `fmugen[nuitka]`. |
| `--hf-weights` | on with `--vendor` / `--compile` | Put the Hugging Face models the model loads into the FMU, which then loads them offline. See [packaging.md](packaging.md#hugging-face-models---hf-weights). |
| `--capture-output` | off | Send what the model prints (stdout and stderr, also from C code) to the importer's log, prefixed `[output]`, instead of the console. Use it for models that print more than a few KB (warnings, progress bars): UniFMU 0.14 crashes when the FMU's Python writes that much to the console, and the importer hangs. The importer may only show these messages with debug logging on. |

On success it prints the FMU path, the FMI version, and the number of variables per causality (and clocks):

```
Built C:\…\out\rc_building.fmu (FMI 2.0; 12 parameters, 3 calculatedParameters, 3 inputs, 4 locals, 5 outputs)
```

It may also print `note:` lines, e.g. when `[events]` is ignored for FMI 2.

`build` imports the model to check the config against its real signatures, but **does not run it**: no object is constructed and no step is made, so models that need hardware, a network or a licence build anywhere. Only `fmugen init` (and `build model.py`, which infers the config the same way) calls the model.

**Examples:**

```bash
fmugen build examples/psychrometry -o out/psychrometry.fmu
```

```bash
fmugen build examples/simple_pid -o out/simple_pid.fmu
```

```bash
fmugen build examples/rc_building -o out/rc_building_fmi3.fmu --fmi 3
```

```bash
fmugen build examples/psychrometry -o out/psychrometry_folder --format folder
```

For another machine with Python (offline install from the FMU):

```bash
fmugen build examples/simple_pid -o out/simple_pid_vendored.fmu --vendor
```

For another machine without Python, with no source code in the FMU:

```bash
fmugen build examples/simple_pid -o out/simple_pid_compiled.fmu --compile pyinstaller
```

### Model targets

| Form | Meaning |
|---|---|
| `path/model.py` | A file; the entry is its only public function or class. |
| `path/model.py:Name` | A file and the function or class `Name` in it. |
| `package.module:Name` | `Name` in an installed module, e.g. `simple_pid:PID`, `filterpy.kalman:KalmanFilter`. |

In `fmugen.toml` the same forms appear as `[model] entry`, with file paths relative to the config's folder.

### Errors and exit codes

| Exit code | Meaning |
|---|---|
| `0` | Success. |
| `2` | A usage or config error, printed as `fmugen: error: …`: an unknown key, a bad value, an import failure, an `init` probe failure, or an existing config without `--force`. |

Each error names the section and key, e.g. `[inputs] x: unknown key(s) ['strat']`. See [Troubleshooting](#8-troubleshooting).

---

## 5. Configuration: `fmugen.toml`

### File layout

```toml
[model]                     # what to call, and how
[model.constants]           # fixed non-FMI arguments: constructor (classes) / function
[model.call_constants]      # fixed non-FMI arguments: step method (classes)
[experiment]                # default experiment, fixed step
[time]                      # arguments that receive the FMU time / step size

[structural_parameters]     # FMI 3 ─┐
[parameters]                #        │
[calculated_parameters]     #        │ FMU variables,
[inputs]                    #        │ one inline table each:
[states]                    #        │ name = { key = value, ... }
[outputs]                   #        │
[locals]                    #       ─┘

[clocks.<name>]             # FMI 3: one table per clock
[events]                    # FMI 3: terminate / next event time
```

- **Paths:** they are relative to the folder containing `fmugen.toml`.
- **Unknown keys:** they are errors, so typos are caught.
- **FMI 3-only keys:** keys and sections marked **FMI 3** are rejected in an FMI 2 build with an error that says how to switch. Otherwise the same file builds either version.

### `[model]`

| Key | Type | Default | Description |
|---|---|---|---|
| `entry` | string | **required** | `"path/file.py:Name"` or `"package.module:Name"`. |
| `fmi_version` | `2` / `3` | `2` | FMI version. `build --fmi` overrides it. |
| `call` | string / `false` | `"__call__"` if the class is callable | Classes: the method run on each step. A **function** entry with `call` set is a factory: it is called once, at the end of initialization, with the parameters (like a constructor), and `call` is the method run on each step on the object it returns, e.g. `entry = "silero_vad:load_silero_vad"`, `call = "__call__"`. `false`: nothing runs on a step and only clocks run code (needs `[clocks]`; also allowed for functions). |
| `kind` | `"function"` | none | Treat a class as a function: construct it with the inputs on every step and read outputs from the new object (`return:<attr>`). |
| `create` | classmethod name | none | Classes only: build the object with this classmethod instead of calling the class, e.g. `"from_pretrained"`. Parameters bound to `init:` (the default) become its arguments. For models loaded from saved weights or files. |
| `save_state` | `true`, `false` or list of attribute names | `true` | How the FMU saves and restores its state (rollback). `true`: the whole model object is pickled (with `cloudpickle` when `pickle` can't, e.g. lambdas). `false`: not supported (`canGetAndSetFMUState="false"`), e.g. for hardware. A list such as `["_state", "_context"]`: only those attributes are saved and put back on restore; the rest of the object (an ONNX session, a device handle) is kept as it is. `fmugen init` sets it by trying to pickle the object. |
| `setup` | list | `[]` | Calls run each time the FMU initializes, before the model is used. See [setup syntax](#value-syntax). |
| `name` | string | the entry's name | `modelName`. `build --name` overrides it. |
| `description` | string | first docstring line of the entry, else of its module | FMU description. |
| `author` | string | `""` | `author`. `build --author` overrides it. |
| `sources` | list of paths | `[]` | Extra files or directories to copy into the FMU, keeping their paths. The entry file is always copied. Their folders go on `sys.path`, so flat and package imports both work. |
| `requirements` | list of strings | `[]` | pip requirement specifiers, e.g. `"simple-pid==2.0.1"`. Written to `resources/requirements.txt`, as a record of what the FMU's environment must contain. They must be installed in the environment fmugen runs in. |
| `init_call` | bool | `true` for functions with a step, else `false` | Call the model when leaving initialization mode to compute initial outputs. States are not advanced by this call. |
| `terminate` | string | none | Classes: a method called on terminate, e.g. `"close"`. |

### `[model.constants]`, `[model.call_constants]`

Fixed keyword arguments that are not FMU variables.
- `constants` go to the constructor (classes) or the function.
- `call_constants` go to the step method (classes only).

Values use the [value syntax](#value-syntax). Each key must be an argument of the target, unless it accepts `**kwargs`. A number key (`0 = ...`) is a positional argument, for `*args` callables (e.g. `nashpy.Game(A)`), numbered together with `to = "pos:N"` variables.

```toml
[model.constants]
output_limits = { python = "(-100.0, 100.0)" }
sample_time = { python = "None" }
heating_supply_system = { ref = "supply_system:HeatPumpAir" }
```

### `[experiment]`

All keys are optional.

| Key | Type | Description |
|---|---|---|
| `start_time` | number | `<DefaultExperiment startTime>`; also the FMU time until the importer sets one. |
| `stop_time` | number | `<DefaultExperiment stopTime>`. |
| `step_size` | number | `<DefaultExperiment stepSize>`. Also used for the initialization call. |
| `tolerance` | number | `<DefaultExperiment tolerance>`. |
| `fixed_step` | bool, default `false` | The model only works with `step_size`: declares `canHandleVariableCommunicationStepSize="false"` and rejects any other step size. Requires `step_size`. |

### `[time]`

Maps an argument of the step function or method (or of a clock's `call`) to the FMU clock:

```toml
[time]
dt = "step_size"
t  = "time"
```

| Value | On a step `doStep(t, h)` | On a clock tick (FMI 3) |
|---|---|---|
| `"time"` | `t` | the event time |
| `"step_size"` | `h` | time since that clock last ticked (its interval on the first tick) |
| `"end_time"` | `t + h` | event time + the above |

### Variable sections

Each line is `name = { … }`. The name is the FMU variable name and must be a Python identifier. In FMI 3, `time` is reserved. Value references are assigned in the order of this table, then (FMI 3) `time`, then clocks.

| Section | FMI causality | Direction | Default binding (class / function) | Section-specific keys |
|---|---|---|---|---|
| `[structural_parameters]` **FMI 3** | `structuralParameter` | importer → model | `init:<name>` / `arg:<name>` | `to`, `attr` |
| `[parameters]` | `parameter` | importer → model | `init:<name>` / `arg:<name>` | `to`, `attr` |
| `[calculated_parameters]` | `calculatedParameter` | model → importer | `attr:<name>` (classes only) | `from` |
| `[inputs]` | `input` | importer → model | `arg:<name>` | `to`, `clocks` |
| `[states]` | `local`, `initial="exact"` | fed back each step | `arg:<name>` | `to`, `next` (required) |
| `[outputs]` | `output` | model → importer | `attr:<name>` / `return:<name>` | `from`, `depends_on`, `clocks` |
| `[locals]` | `local` | model → importer | as outputs | `from`, `clocks` |

### Variable keys

These keys apply to every section, unless marked.

| Key | Type | Default | Description |
|---|---|---|---|
| `type` | string | see [Types](#types) | FMI type. |
| `start` | value / list | see below | Start value. Arrays: a flat row-major list, or one value for every element. Enumeration: item name or 1-based index. Binary: hex string. |
| `unit` | string | none | Floating-point only. Informational; listed in `<UnitDefinitions>`. |
| `description` | string | none | |
| `quantity` | string | none | e.g. `"ThermodynamicTemperature"`. |
| `min`, `max` | number | none | Numeric and Enumeration. Declared, not enforced. |
| `nominal` | number | none | Floating-point only. |
| `variability` | string | parameters: `fixed`; floats: `continuous`; others and clocked: `discrete` | Parameters and structural parameters: `fixed`/`tunable`. Inputs: `discrete`/`continuous`. Outputs and locals: also `constant`. |
| `initial` | string | see below | Override the FMI `initial` attribute where FMI allows a choice. |
| `items` | list of strings | none | Enumeration items, numbered from 1; the model receives the integer. |
| `enum` | string | none | `"module:EnumClass"`; the model receives and returns enum members. |
| `dimensions` **FMI 3** | list | none | Array: sizes (`[3]`) and/or structural parameter names (`["n", 2]`). |
| `numpy` | bool | `false` | Arrays passed into the model are `numpy.ndarray` instead of nested lists. |
| `convert` | `"module:function"` | none | Values passed to the model (parameters, inputs, states): call this function on the value first, e.g. `"torch:tensor"`, `"jax.numpy:asarray"`. `init` sets it from `torch.Tensor`, JAX and TensorFlow annotations. |
| `clocks` **FMI 3** | list of one clock name | none | Inputs, outputs and locals: the variable belongs to that clock. |
| `to` | binding | see table above | Where an input-like value goes. See [Bindings](#bindings-to-from-next). |
| `from` | binding | see table above | Where an output-like value comes from. |
| `next` | binding | **required** in `[states]` | Where a state's next value comes from. |
| `attr` | string / `false` | the `to` name | Tunable class parameters: the attribute written when the value changes after initialization; `false` means the constructor only. |
| `depends_on` | list of input names | all inputs | Outputs: `<ModelStructure>` dependencies. |

**Start values and `initial`:**

| Section | Without `start` | With `start` |
|---|---|---|
| structural parameters, parameters, inputs, states | start = type default (0, `false`, `""`, first item) | as given |
| outputs | `initial="calculated"` | `initial="exact"`; reported until the model produces a value |
| locals, calculated parameters | `initial="calculated"` | `initial="approx"` |

### Bindings: `to`, `from`, `next`

**`to`**: where a value goes. Used in parameters, structural parameters, inputs and states.

| Form | For | Meaning |
|---|---|---|
| `"init:<arg>"` | classes | Constructor keyword argument, used when the object is built at the end of initialization. |
| `"arg:<arg>"` | both | Keyword argument of the function or step method. For a clocked input: of the clock's `call`. |
| `"pos:<N>"` | both | Positional argument N (0, 1, … without gaps). For positional-only arguments, e.g. in C extensions. |
| `"attr:<path>"` | classes | Attribute set after construction and before every step (or tick, for clocked inputs). Dotted paths are allowed. |
| `"call:<method>"` | classes | Setter method called with the value after construction and before every step, e.g. `Q1(value)`. |
| `"arg:<arg>[<i>]"`, `"arg:<arg>[<key>]"` | both | Item of a tuple or dict argument: variables bound to items of the same argument are put together into a tuple (0, 1, … without gaps) or a dict. `init` splits tuple and dict `--start` values this way. |

**`from`** (outputs, locals, calculated parameters) and **`next`** (states): where a value comes from.

| Form | Meaning |
|---|---|
| `"return"` | The whole return value of the step (or clock call). |
| `"return:<key>"` | `result[key]` for a dict, `result[int(key)]` for a tuple or list, else `result.key`. |
| `"attr:<path>"` | Classes: an attribute or property of the object after the step. Dotted paths are allowed. Calculated parameters must use this form. |

Arguments named by `init:`, `arg:` and `[time]` must exist in the target's signature, unless it accepts `**kwargs`.

### Types

| `type` | FMI 2 | FMI 3 | Python value |
|---|---|---|---|
| `Real`, `Float64` | `Real` | `Float64` | `float` |
| `Float32` | — | `Float32` | `float` |
| `Integer`, `Int32` | `Integer` | `Int32` | `int` |
| `Int8`, `UInt8`, `Int16`, `UInt16`, `UInt32`, `Int64`, `UInt64` | — | same | `int`, range-checked |
| `Boolean` | `Boolean` | `Boolean` | `bool` |
| `String` | `String` | `String` | `str` |
| `Binary` | — | `Binary` | `bytes` (start: hex string) |
| `Enumeration` | `Enumeration` | `Enumeration` | `int`, or enum member with `enum` |

Without `type`, the type comes from `start`: `bool` → Boolean, `int` → Integer, `str` → String, otherwise Real. `items`/`enum` make it an Enumeration. Structural parameters default to `UInt64`.

### `[clocks.<name>]`

**FMI 3 only.** One table per clock.

| Key | Type | Default | Description |
|---|---|---|---|
| `causality` | `"input"` / `"output"` | `"input"` | Input: ticked by the importer. Output: ticked by the model. |
| `interval_variability` | string | `"constant"` with `interval`, else `"triggered"` | `constant`, `fixed`, `tunable` (periodic: need `interval`); `changing`, `countdown` (need `interval_from`); `triggered` (aperiodic). Output clocks: `triggered` only. |
| `interval` | seconds | none | Periodic input clocks. |
| `shift` | seconds | `0.0` | Periodic input clocks: offset of the first tick. |
| `interval_from` | `from` binding | none | `changing`/`countdown`: where the model's next interval is read. |
| `call` | string | none | Input clocks: what runs on a tick. A method name (classes), a function in the entry's module, or `"module:function"`. Required if the clock has clocked inputs. |
| `from` | `from` binding | **required** for output clocks | The value that ticks the clock when true after a step or tick. |
| `description` | string | none | |

```toml
[clocks.sample]          # periodic input clock
interval = 0.1
call = "__call__"

[clocks.measurement]     # triggered input clock
call = "update"

[clocks.overflow]        # output clock
causality = "output"
from = "attr:overflowed"
```

### `[events]`

**FMI 3 only**; ignored, with a note, for FMI 2.

| Key | Value | Description |
|---|---|---|
| `terminate` | `from` binding | When true after a step or tick, the FMU reports `terminateSimulation`. |
| `next_event_time` | `from` binding | Reported by `updateDiscreteStates` as the next event time. |

### Value syntax

**Constants, and setup arguments in table form:**

| Form | Passed as |
|---|---|
| TOML string, number, bool, array, table | that value (arrays become lists) |
| `{ python = "<literal>" }` | `ast.literal_eval`, e.g. `"None"`, `"(0, 100)"` |
| `{ ref = "module:attr" }` or `{ ref = "module.attr" }` | the imported object |
| `{ call = "module:function(args)" }` | the result of calling it when the FMU initializes. Arguments are literals, dotted names of importable objects or builtins, calls of those (`numpy.linspace(0, 20, 200)`, `float("inf")`), and lists, tuples and dicts of these; keyword arguments allowed. Without parentheses, `"module:attr.path"` is the object itself, not called: a function to pass (`"numpy:sin"`) or an enum member (`"pyfluids:FluidsList.Water"`). `init --probe` stops if the call fails. Example: `"huggingface_sb3:load_from_hub(repo_id='sb3/demo-hf-CartPole-v1', filename='ppo-CartPole-v1.zip')"`. `init --start "NAME=call:..."` writes it. |

**Setup calls** (`[model] setup`, `init --setup`):

| Form | When it runs |
|---|---|
| `"module:function"`, `"module:function(arg, ...)"` | Before the model object is constructed (or the function first called). |
| `"method"`, `"method(arg, ...)"` | On the object, right after construction (classes). |
| `{ call = "...", args = [...], kwargs = {...} }` | As above, with arguments in the [constant forms](#value-syntax). |

String-form arguments are Python literals or dotted names of importable objects, e.g. `"psychrolib:SetUnitSystem(psychrolib.SI)"`. Setup runs every time the FMU initializes, including after a reset.

### Validation rules

`build` rejects a config with a clear message when:

- it has an unknown section or key, or is missing `[model] entry`;
- a binding names an argument the target doesn't have;
- two variables, or a variable and a clock, share a name;
- a type, `variability` or `initial` doesn't fit the section or FMI version;
- a start value is invalid for its type (wrong kind, out of range, bad hex);
- `pos:` indices have gaps, a state has no `next`, or a clocked input's clock has no `call`;
- `fixed_step` is set without `step_size`, or `call = false` is set without clocks;
- it defines no variables at all;
- an FMI 3-only feature is used in an FMI 2 build.

The model itself is not run: errors in the model show up when the FMU runs, or earlier in `fmugen init`.

---

## 6. Complete example

An FMI 3 config that uses most sections. Each key is explained above.

```toml
[model]
entry = "plant.py:Plant"            # your file and class
fmi_version = 3
call = "step"
setup = ["reset"]                   # plant.reset() after construction
sources = ["lib"]                   # local helper package
requirements = ["numpy>=2"]
name = "plant"
description = "Example plant"
author = "Me"

[model.constants]
solver = "rk4"                      # a constructor argument that isn't an FMU variable

[experiment]
step_size = 0.1
stop_time = 60.0

[time]
dt = "step_size"

[structural_parameters]
n = { start = 3, description = "number of zones" }

[parameters]
area = { start = 2.0, unit = "m2" }                              # Plant(area=...)
gain = { start = 1.0, variability = "tunable" }                  # also plant.gain = ... later
temps0 = { dimensions = ["n"], start = 20.0, unit = "degC", to = "attr:temps", numpy = true }

[calculated_parameters]
volume = { unit = "m3" }                                         # plant.volume after construction

[inputs]
heat = { start = 0.0, unit = "W" }                               # step(heat=...)
valve = { start = 1, type = "UInt8", to = "call:set_valve" }     # plant.set_valve(value)
sensor = { start = 0.0, clocks = ["sample"] }                    # passed to plant.sample(sensor=...)

[states]
level_prev = { start = 0.5, unit = "m", next = "return:level" }

[outputs]
level = { from = "return:level", unit = "m" }
temps = { dimensions = ["n"], unit = "degC" }                    # plant.temps
alarm = { start = false }

[locals]
energy = { unit = "J" }

[clocks.sample]
interval = 1.0
call = "sample"


[clocks.overheat]
causality = "output"
from = "attr:overheated"

[events]
terminate = "attr:done"
```

This config is illustrative: `plant.py` is not part of the repository. Every key in it is validated by `fmugen` the same way as in the [examples](../examples).

---

## 7. Recipes

| I want to… | Use |
|---|---|
| Package a plain function | `fmugen init model.py` → `build` |
| Use a class with a step method | `--call METHOD` (or `[model] call`) |
| Give arguments without defaults sensible values | `init --start NAME=VALUE` / `start = …` |
| Call a library setup function first | `[model] setup = ["module:function(args)"]` |
| Reset a gym-style environment before stepping | `setup = ["reset"]` |
| Feed a result back into the next step | `[states] x_prev = { next = "return:x" }` |
| Pass the FMU step size or time | `[time] dt = "step_size"`, `t = "time"` |
| Change a parameter during the simulation | `variability = "tunable"` |
| Expose a value the constructor computes | `[calculated_parameters]` |
| Bind a C extension's positional arguments | `to = "pos:N"` |
| Set an input through a method | `to = "call:method"` |
| Wrap a class whose constructor does everything | `[model] kind = "function"` |
| Use a model from PyPI | install it in the environment, `entry = "pkg.module:Name"`, `requirements` |
| Use matrices/vectors | FMI 3 `dimensions`, `numpy = true` |
| Size arrays from a constructor argument | FMI 3 `[structural_parameters]` |
| Run code on events, not every step | FMI 3 `[clocks.<name>]`, `clocks = [...]`, `call = false` |
| Let the model stop the simulation | FMI 3 `[events] terminate` |
| Only allow one step size | `[experiment] fixed_step = true` |
| Build both FMI versions from one config | `build --fmi 2` / `build --fmi 3` |

---

## 8. Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `cannot import …: No module named …` | The model's package isn't in the environment running fmugen. | `pip install <pkg>` in that environment. |
| `probe call failed (…)` in the config written by `init --probe` | The model raised an error at the start values (division by zero, `log(0)`, out of range…). | Rerun `init` with realistic `--start` values. |
| `… must be called first` / `has not been defined` (raised by the model) | The library needs setup. | `[model] setup` / `init --setup`. |
| `--start NAME: arrays and bytes need --fmi 3` | An array or Binary value in an FMI 2 build. | Use `--fmi 3`. |
| `--start names that are not arguments of the model` | A typo, or the argument isn't in the inspected signature. | Check the names; for C extensions, write the config by hand. |
| `the config defines no FMU variables` | Nothing could be inferred (e.g. `**kwargs` only, or an uninspectable signature). | Add `[inputs]` and `[outputs]`, or use `--start`, `--kind function`. |
| `requires FMI 3 (…)` | FMI 3-only feature in an FMI 2 build. | `fmi_version = 3` or `build --fmi 3`. |
| `cannot inspect the signature of …` (comment in the generated config) | A C extension without signature information. | Hand-written variables with `to = "pos:N"`. |
| `unknown key(s) [...]` | A typo in a key. | The message lists the allowed keys. |
| `duplicate variable or clock names` | The same name in two sections, or a variable named like a clock. | Rename one; bind it with `to`/`from`. |
| `save_state = false` or `save_state = [...]` written by `init`, with a comment | The object holds something that can't be pickled: an ONNX session, a file, a socket, a generator. | Fine for most uses. With a list, check that the attributes named as not saved don't change during a simulation (a session or device handle doesn't; a generator does): if they do, set `save_state = false`. |
| The FMU fails at runtime with `ModuleNotFoundError` | The environment the FMU was built in has changed or was deleted. | Reinstall the package there, or rebuild the FMU from the environment that has it. |
| The importer hangs; the console shows `panicked at ... zeromq-0.4.1/src/rep.rs:168:40: not yet implemented` | The model printed more than about 4 KB (warnings, progress bars); UniFMU 0.14 crashes on that. | Rebuild with `--capture-output`. |
| The simulation hangs or the importer reports an unknown command | The importer called an FMI function the UniFMU backend lacks. | See [fmi.md](fmi.md#unsupported-functions). |
