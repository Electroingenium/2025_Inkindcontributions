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

```bash
uv sync
```

This installs Python 3.13, the dependencies and the `fmugen` command. Run it as `uv run fmugen …`, or as `fmugen …` inside the activated `.venv`.

You also need [UniFMU](https://github.com/INTO-CPS-Association/unifmu/releases) **0.14.0** (exactly this version) for `fmugen build`. fmugen runs `unifmu generate` to get each FMU's native binaries and Python backend. Put `unifmu` on `PATH`, or set the environment variable `FMUGEN_UNIFMU` to the executable. `fmugen init` works without it.

Libraries your model imports must be installed in the same environment, so that `init` and `build` can import them (`uv add …`, or `uv run --with <package> fmugen …`). They must also be available to the Python that runs the FMU; see [`--python`](#fmugen-build) and [`--vendor`](#fmugen-build).

---

## 3. Workflow

```
your model ──► fmugen init ──► fmugen.toml ──► (review & edit) ──► fmugen build ──► model.fmu
```

1. Infer a config:

   ```bash
   uv run fmugen init path/to/model.py
   ```

2. Review `path/to/fmugen.toml`. Check the start values, add units, and remove what you don't need.
3. Build:

   ```bash
   uv run fmugen build path/to/fmugen.toml -o out/model.fmu --python
   ```

4. Check the FMU:

   ```bash
   uv run fmpy validate out/model.fmu
   ```

   ```bash
   uv run fmpy simulate out/model.fmu --output-file out/result.csv
   ```

For a quick try, `fmugen build path/to/model.py -o out/model.fmu` skips step 2: the config is inferred in memory.

---

## 4. Commands

```
fmugen init  MODEL [options]
fmugen build MODEL -o OUTPUT [options]
```

### `fmugen init`

Imports the model, inspects its function or class, makes **one probe call** with the start values to discover its results, and writes a commented `fmugen.toml`.

```
fmugen init MODEL [-o OUTPUT] [--call METHOD] [--fmi {2,3}]
                  [--start NAME=VALUE ...] [--setup CALL ...] [--kind function] [--force]
```

| Option | Default | Description |
|---|---|---|
| `MODEL` | required | A [model target](#model-targets): `model.py`, `model.py:Name` or `package.module:Name`. |
| `-o`, `--output PATH` | `fmugen.toml` next to the model (current directory for an installed module) | Where to write the config; missing folders are created. `-o -` prints it instead. A model file must be inside the config's folder. |
| `--call METHOD` | `step`, `do_step`, `update`, `__call__`, or the only public method | Classes: the method run on each step. |
| `--fmi {2,3}` | none (FMI 2) | Writes `fmi_version` into the config. With `3`, list/tuple/numpy values are inferred as arrays, `bytes` as Binary and numpy `float32` as Float32. |
| `--start NAME=VALUE` | none | Start and probe value for an argument; repeatable. `VALUE` is a Python literal (`1e5`, `"Water"`, `[1.0, 0.0]`); a bare word is taken as a string. Use it for arguments without a default, or whose default breaks the model. |
| `--setup CALL` | none | A [setup call](#model) to run before the probe; it is also written to `[model] setup`. Repeatable. E.g. `"psychrolib:SetUnitSystem(psychrolib.SI)"`, `reset`. |
| `--kind function` | none | Treat a class whose constructor does the work as a function called on every step (writes `[model] kind`). |
| `--force` | off | Overwrite an existing config. |

**Where `--start` values go.** If a name is an argument of both the constructor and the step method, the value goes to the one that has no default; on a tie, to the step method. A name that neither declares goes to whichever accepts `**kwargs`, the step method first. A name that matches nothing is an error.

**What `init` infers:**

| | From |
|---|---|
| Entry | the name after `:`; else the only public function or class defined in the module |
| Inputs (functions) / parameters (classes) | arguments with a `bool`/`int`/`float`/`str` default, without a default, or given `--start` |
| Start values and types | the default or `--start` value; otherwise the annotation; otherwise Real `0.0` |
| Time arguments | arguments named `dt`, `step_size`, `h` (step size) or `t`, `time` (time) |
| Outputs from the return value | dict keys, tuple positions (`y0`, `y1`, …), a single value (`y`), or an object's attributes |
| Class outputs and locals | public attributes the probe step created (outputs) or changed (locals), and readable properties (outputs) |
| States | an input `x_prev` whose next value is returned or stored as `x_next` or `x` |
| Sources | local modules under the config's folder that the model imported |
| Positional-only arguments | bound with `to = "pos:N"` |
| Constants | non-FMI defaults (`None`, tuples, objects), written as commented-out examples |

**Not inferred:** units, descriptions, tunable variability (suggested in comments), states with other names, clocks, events, setter-method inputs (`call:`), and anything the probe couldn't reach. If the probe fails, `init` still writes the config and says why in a comment.

**Examples:**

```bash
uv run fmugen init examples/psychrometry/psychrometry.py -o -
```

```bash
uv run fmugen init simple_pid:PID -o pid/fmugen.toml
```

```bash
uv run --with fluids fmugen init fluids.friction:friction_factor --start Re=1e5 -o -
```

```bash
uv run --with psychrolib fmugen init psychrolib:GetHumRatioFromRelHum --setup "psychrolib:SetUnitSystem(psychrolib.SI)" --start TDryBulb=25.0 --start RelHum=0.5 --start Pressure=101325.0 -o -
```

```bash
uv run fmugen init filterpy.kalman:KalmanFilter --call predict --fmi 3 --start dim_x=2 --start dim_z=1 -o -
```

### `fmugen build`

Packages the model into an FMU. Before writing the FMU, it runs the packaged model once through the real adapter: initialization, one tick of each input clock (FMI 3), one step, and saving and restoring state. A model that fails there fails the build with the model's own error.

```
fmugen build MODEL -o OUTPUT [--fmi {2,3}] [--format {fmu,folder}] [--python [PATH]]
                   [--vendor] [--name NAME] [--author AUTHOR] [--call METHOD]
```

| Option | Default | Description |
|---|---|---|
| `MODEL` | required | A `fmugen.toml`, a directory containing one, or a [model target](#model-targets). For a model target, the config is inferred in memory, as `init` would without options. |
| `-o`, `--output PATH` | required | Output path, used exactly as given. Parent directories are created. |
| `--fmi {2,3}` | `[model] fmi_version`, else `2` | FMI version to build. |
| `--format {fmu,folder}` | `fmu` | `fmu`: zipped `.fmu` archive. `folder`: unzipped UniFMU folder. |
| `--python [PATH]` | not set: the FMU runs `python` from `PATH` on Windows | Python executable written into `resources/launch.toml` for Windows. The flag alone uses the current interpreter. Handy locally; the FMU then only works on this machine. |
| `--vendor` | off | Install `[model] requirements` into the FMU (`resources/site/`), so the target Python doesn't need them. |
| `--name NAME` | `[model] name`, else the entry's name | `modelName` in `modelDescription.xml`. |
| `--author AUTHOR` | `[model] author`, else empty | `author` in `modelDescription.xml`. |
| `--call METHOD` | as `init` | Only when `MODEL` is a model target with a class. |

On success it prints the FMU path, the FMI version, and the number of variables per causality (and clocks):

```
Built C:\…\out\rc_building.fmu (FMI 2.0; 12 parameters, 3 calculatedParameters, 3 inputs, 4 locals, 5 outputs)
```

It may also print `note:` lines, e.g. when FMU state saving was turned off because the model object can't be pickled, or when `[events]` is ignored for FMI 2.

**Examples:**

```bash
uv run fmugen build examples/psychrometry -o out/psychrometry.fmu --python
```

```bash
uv run fmugen build examples/simple_pid -o out/simple_pid.fmu --python --vendor
```

```bash
uv run fmugen build examples/rc_building -o out/rc_building_fmi3.fmu --python --fmi 3
```

```bash
uv run fmugen build examples/psychrometry -o out/psychrometry_folder --format folder
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
| `2` | A usage or config error, printed as `fmugen: error: …`: an unknown key, a bad value, an import failure, a probe failure, or an existing config without `--force`. |

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
| `call` | string / `false` | `"__call__"` if the class is callable | Classes: the method run on each step. `false`: nothing runs on a step and only clocks run code (needs `[clocks]`; also allowed for functions). |
| `kind` | `"function"` | none | Treat a class as a function: construct it with the inputs on every step and read outputs from the new object (`return:<attr>`). |
| `setup` | list | `[]` | Calls run each time the FMU initializes, before the model is used. See [setup syntax](#value-syntax). |
| `name` | string | the entry's name | `modelName`. `build --name` overrides it. |
| `description` | string | first docstring line of the entry, else of its module | FMU description. |
| `author` | string | `""` | `author`. `build --author` overrides it. |
| `sources` | list of paths | `[]` | Extra files or directories to copy into the FMU, keeping their paths. The entry file is always copied. Their folders go on `sys.path`, so flat and package imports both work. |
| `requirements` | list of strings | `[]` | pip requirement specifiers, e.g. `"simple-pid==2.0.1"`. Written to `resources/requirements.txt`; installed into the FMU with `build --vendor`. |
| `init_call` | bool | `true` for functions with a step, else `false` | Call the model when leaving initialization mode to compute initial outputs. States are not advanced by this call. |
| `terminate` | string | none | Classes: a method called on terminate, e.g. `"close"`. |

### `[model.constants]`, `[model.call_constants]`

Fixed keyword arguments that are not FMU variables.
- `constants` go to the constructor (classes) or the function.
- `call_constants` go to the step method (classes only).

Values use the [value syntax](#value-syntax). Each key must be an argument of the target, unless it accepts `**kwargs`.

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
| `step_size` | number | `<DefaultExperiment stepSize>`. Also used for the initialization call and the build probe (default `1.0`). |
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
| `numpy` **FMI 3** | bool | `false` | Arrays passed into the model are `numpy.ndarray` instead of nested lists. |
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
- an FMI 3-only feature is used in an FMI 2 build;
- the build probe (one real initialization and step) fails.

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
| Use a model from PyPI | `entry = "pkg.module:Name"`, `requirements`, `build --vendor` |
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
| `cannot import …: No module named …` | The model's package isn't in the environment running fmugen. | `uv add <pkg>`, or `uv run --with <pkg> fmugen …`. |
| `probe … failed:` followed by a traceback | The model raised an error at the start values (division by zero, `log(0)`, out of range…). | Give realistic `start` values, or `init --start`. |
| `… must be called first` / `has not been defined` (raised by the model) | The library needs setup. | `[model] setup` / `init --setup`. |
| `--start NAME: arrays and bytes need --fmi 3` | An array or Binary value in an FMI 2 build. | Use `--fmi 3`. |
| `--start names that are not arguments of the model` | A typo, or the argument isn't in the inspected signature. | Check the names; for C extensions, write the config by hand. |
| `the config defines no FMU variables` | Nothing could be inferred (e.g. `**kwargs` only, or an uninspectable signature). | Add `[inputs]` and `[outputs]`, or use `--start`, `--kind function`. |
| `requires FMI 3 (…)` | FMI 3-only feature in an FMI 2 build. | `fmi_version = 3` or `build --fmi 3`. |
| `cannot inspect the signature of …` (comment in the generated config) | A C extension without signature information. | Hand-written variables with `to = "pos:N"`. |
| `unknown key(s) [...]` | A typo in a key. | The message lists the allowed keys. |
| `duplicate variable or clock names` | The same name in two sections, or a variable named like a clock. | Rename one; bind it with `to`/`from`. |
| `note: the model object cannot be pickled …` | The object holds a file, socket or generator. | Fine for most uses; FMU state saving and restoring is disabled. |
| The FMU fails at runtime with `ModuleNotFoundError` | The Python running the FMU lacks a requirement. | `build --vendor`, `build --python`, or install it there. |
| The simulation hangs or the importer reports an unknown command | The importer called an FMI function the UniFMU backend lacks. | See [fmi.md](fmi.md#unsupported-functions). |
