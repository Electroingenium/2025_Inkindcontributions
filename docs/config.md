# `fmugen.toml` reference

`fmugen.toml` describes how an unmodified Python model becomes an FMU. For worked examples of each key, see [models.md](models.md) and the configs in [tested-models.md](tested-models.md). It sits in the model's folder, and every path in it is relative to that folder. `fmugen init` writes a first version (see [models.md](models.md#what-fmugen-init-infers)). This page lists every key.

Unknown keys are rejected with an error, so typos don't go unnoticed. Keys marked **FMI 3** are only accepted when building FMI 3 (`[model] fmi_version = 3` or `fmugen build --fmi 3`). Building such a config as FMI 2 fails with an error that says so. Otherwise the same config builds either version.

```toml
[model]                     # what to call
[model.constants]           # fixed non-FMI arguments (constructor / function)
[model.call_constants]      # fixed non-FMI arguments (step method)
[experiment]                # default experiment and step-size capability
[time]                      # arguments that receive the FMU time / step size
[structural_parameters]     # FMI 3: FMU variables, one inline table each ...
[parameters]
[calculated_parameters]
[inputs]
[states]
[outputs]
[locals]
[clocks.<name>]             # FMI 3: one table per clock
[events]                    # FMI 3: terminate / next event time
```

---

## `[model]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `entry` | string | **required** | `"path/file.py:Name"` (a file under this folder) or `"package.module:Name"` (an installed module). `Name` is a function or a class. |
| `fmi_version` | `2` or `3` | `2` | FMI version to build. `fmugen build --fmi` overrides it. |
| `call` | string or `false` | `"__call__"` if the class is callable | Classes: the method run on each step. A **function** entry with `call` set is a factory: it is called once, at the end of initialization, with the parameters (like a constructor), and `call` is the method run on each step on the object it returns, e.g. `entry = "silero_vad:load_silero_vad"`, `call = "__call__"`. `false` (classes and functions; needs `[clocks]`): nothing runs on `doStep`, only clocks run code. |
| `name` | string | the entry's name | `modelName` in `modelDescription.xml`. `fmugen build --name` overrides it. |
| `description` | string | first line of the entry's docstring, else the module's | `description` in `modelDescription.xml`. |
| `author` | string | `""` | `author` in `modelDescription.xml`. `fmugen build --author` overrides it. |
| `sources` | list of strings | `[]` | Extra files and directories to copy into the FMU, keeping their paths. A file entry is always copied. |
| `requirements` | list of strings | `[]` | pip requirement specifiers the model needs at runtime. See [packaging.md](packaging.md#the-fmus-python-environment). |
| `kind` | `"function"` | none | Treat a class as a function: construct it with the inputs on every step and read outputs from the new object (`return:<attr>`). For classes whose constructor does all the work. |
| `create` | classmethod name | none | Classes only: build the object with this classmethod instead of calling the class, e.g. `"from_pretrained"`. Parameters bound to `init:` (the default) become its arguments. For models loaded from saved weights or files. |
| `setup` | list | `[]` | Calls run when the FMU initializes, before the model is used. `"module:function"` or `"module:function(args)"` runs before the class is constructed (e.g. `"psychrolib:SetUnitSystem(psychrolib.SI)"`). A bare `"method"` or `"method(args)"` runs on the object right after construction (e.g. `"reset"`). Arguments are Python literals or dotted names of importable objects. The table form `{ call = "...", args = [...], kwargs = {...} }` takes the same values as `[model.constants]`. |
| `init_call` | bool | `true` for functions with a step, `false` otherwise | Call the function or step method when leaving initialization mode, to compute the initial outputs. States are not advanced by this call. |
| `terminate` | string | none | Classes only: a method called on `fmi2Terminate`/`fmi3Terminate` (for example `"close"`). |

### `[model.constants]` and `[model.call_constants]`

These are fixed keyword arguments that are not FMU variables, typically values that FMI can't represent.
- `constants` go to the constructor (classes) or to the function (functions).
- `call_constants` go to the step method (classes only).

| Value | Passed to the model as |
|---|---|
| a TOML string, number, bool, array or table | that value (an array becomes a list) |
| `{ python = "<literal>" }` | `ast.literal_eval(literal)`, e.g. `"None"`, `"(0, 100)"`, `"{'a': 1}"` |
| `{ ref = "module:attr.path" }` or `{ ref = "module.attr" }` | the imported object, e.g. a class or function |
| `{ call = "module:function(args)" }` | the result of calling it when the FMU initializes. Arguments are literals or dotted names, keyword arguments allowed, e.g. `"huggingface_sb3:load_from_hub(repo_id='sb3/demo-hf-CartPole-v1', filename='ppo-CartPole-v1.zip')"`. `init --start "NAME=call:..."` writes it. |

Every key must be an argument of the constructor, function or method (unless it accepts `**kwargs`).

---

## `[experiment]`

All keys are optional.

| Key | Type | Meaning |
|---|---|---|
| `start_time` | number | `DefaultExperiment startTime`; also the FMU's time before the importer sets one. |
| `stop_time` | number | `DefaultExperiment stopTime`. |
| `step_size` | number | `DefaultExperiment stepSize`. Also used for the initialization call and the build probe (default 1.0). |
| `tolerance` | number | `DefaultExperiment tolerance`. |
| `fixed_step` | bool, default `false` | The model only works with `step_size`: writes `canHandleVariableCommunicationStepSize="false"`, and a `doStep` with any other step size returns an error. Requires `step_size`. |

---

## `[time]`

Each key is an argument of the step function or method (or of a clock's `call` that accepts it); its value says what to pass:

| Value | Passed on a step | Passed on a clock tick (FMI 3) |
|---|---|---|
| `"time"` | `t`, the communication point at the start of the step | the event time |
| `"step_size"` | `h`, the communication step size | time since the clock last ticked (its interval on the first tick) |
| `"end_time"` | `t + h` | the event time + the above |

```toml
[time]
dt = "step_size"
```

---

## Variables

Each variable is one line: `name = { key = value, ... }`. The name is the FMU variable name and must be a valid Python identifier; in FMI 3, `time` is reserved for the independent variable. Variables get value references in this order: structural parameters, parameters, calculated parameters, inputs, states, outputs, locals, then (FMI 3) `time`, then clocks.

| Section | FMI causality | Value flows | Default binding |
|---|---|---|---|
| `[structural_parameters]` **FMI 3** | `structuralParameter` | importer → model | class: `init:<name>`; function: `arg:<name>` |
| `[parameters]` | `parameter` | importer → model | class: constructor argument `init:<name>`; function: `arg:<name>` |
| `[calculated_parameters]` | `calculatedParameter` | model → importer | `attr:<name>` (classes only) |
| `[inputs]` | `input` | importer → model | `arg:<name>` |
| `[states]` | `local`, `initial="exact"` | fed back each step | `arg:<name>`, plus the required `next` |
| `[outputs]` | `output` | model → importer | class: `attr:<name>`; function: `return:<name>` |
| `[locals]` | `local` | model → importer | as outputs |

### Types

| `type` | FMI 2 | FMI 3 | Python value |
|---|---|---|---|
| `Real` | `Real` | `Float64` | `float` |
| `Float64` | `Real` | `Float64` | `float` |
| `Float32` | — | `Float32` | `float` |
| `Integer` | `Integer` | `Int32` | `int` |
| `Int32` | `Integer` | `Int32` | `int` |
| `Int8`, `UInt8`, `Int16`, `UInt16`, `UInt32`, `Int64`, `UInt64` | — | same | `int` (range-checked) |
| `Boolean` | `Boolean` | `Boolean` | `bool` |
| `String` | `String` | `String` | `str` |
| `Binary` | — | `Binary` | `bytes`; `start` is a hex string, e.g. `"0aff"` |
| `Enumeration` | `Enumeration` | `Enumeration` | `int`, or the `Enum` member with `enum` |

Without `type`, it comes from `start`: `bool` → Boolean, `int` → Integer, `str` → String, otherwise Real. `items` or `enum` make it an Enumeration. Structural parameters default to `UInt64`.

### Keys for every variable

| Key | Type | Default | Meaning |
|---|---|---|---|
| `type` | string | see [Types](#types) | The FMI type. |
| `start` | value, or list for arrays | see below | Start value. An Enumeration takes an item name or a 1-based index. An array takes a flat list (row-major) or one value for every element. |
| `unit` | string | none | Floating-point only. Added to `<UnitDefinitions>`; informational. |
| `description` | string | none | Variable description. |
| `quantity` | string | none | Physical quantity, e.g. `"ThermodynamicTemperature"`. |
| `min`, `max` | number | none | Numeric types and Enumeration. Declared range; not enforced by the adapter. |
| `nominal` | number | none | Floating-point only. |
| `variability` | string | parameters: `fixed`; others: `continuous` for unclocked floating-point, `discrete` otherwise | parameters and structural parameters: `fixed`/`tunable`; inputs: `discrete`/`continuous`; outputs and locals: also `constant`. |
| `initial` | string | see below | Overrides the FMI `initial` attribute where FMI allows a choice. |
| `items` | list of strings | none | Enumeration items, numbered from 1. The model receives the integer. |
| `enum` | string | none | `"module:EnumClass"`: items are the enum's members, and the model receives and returns members. |
| `dimensions` **FMI 3** | list | none | Makes the variable an array. Each entry is a size (`3`) or the name of a structural parameter (`"n"`). |
| `numpy` **FMI 3** | bool | `false` | Arrays only: pass the value to the model as a `numpy.ndarray` instead of nested lists. Values coming back are accepted either way. |
| `convert` | `"module:function"` | none | Values passed to the model (parameters, inputs, states): call this function on the value first, e.g. `"torch:tensor"`, `"jax.numpy:asarray"`. `init` sets it from `torch.Tensor`, JAX and TensorFlow annotations. |
| `clocks` **FMI 3** | list with one clock name | none | Inputs, outputs and locals: the variable belongs to that clock (see [`[clocks.<name>]`](#clocksname-fmi-3)). |

**Start values and `initial`:**
- **Structural parameters, parameters, inputs, states:** always have a start value. If you don't give one, it is 0 / `false` / `""` / empty / the first item.
- **Outputs without `start`:** `initial="calculated"`. **With `start`:** `initial="exact"`, and the start value is reported until the model produces a value (e.g. before the first step).
- **Locals and calculated parameters without `start`:** `initial="calculated"`. **With `start`:** `initial="approx"`.

### Binding keys

| Key | Sections | Value | Meaning |
|---|---|---|---|
| `to` | structural parameters, parameters, inputs, states | `"init:<arg>"` | Constructor argument (classes). |
| | | `"arg:<arg>"` | Argument of the function or step method; for a clocked input, of the clock's `call`. |
| | | `"call:<method>"` | A setter method called with the value after construction and before every step (classes), e.g. tclab's `Q1(value)`. |
| | | `"pos:<N>"` | Positional argument number N (0, 1, … without gaps) of the function or step method, for positional-only arguments such as those of C extensions. |
| | | `"attr:<name>"` | Attribute set on the object after construction and before every step (classes); clocked: before every tick. Dotted paths allowed. |
| | | `"arg:<arg>[<i>]"`, `"arg:<arg>[<key>]"` | Item `i` of a tuple argument, or key `key` of a dict argument: the variables bound to the items of one argument are put together into a tuple (items 0, 1, … without gaps) or a dict, e.g. torchani's `forward((species, coordinates))`. `init` splits a tuple or dict `--start` value this way. Also `"init:<arg>[…]"`. |
| `from` | outputs, locals, calculated_parameters | `"return"` | The whole return value. |
| | | `"return:<key>"` | `result[key]` for a dict, `result[int(key)]` for a tuple or list, else `result.key`. |
| | | `"attr:<name>"` | An attribute of the object after the step (classes). Dotted paths allowed. Calculated parameters must use this form. |
| `next` | states (**required**) | same forms as `from` | Where the state's value for the next step comes from. |
| `attr` | parameters, structural parameters | string or `false` | Tunable class parameters: the attribute written when the importer changes the value after initialization. Defaults to the parameter's `to` name. `false` means it is passed only to the constructor. |
| `depends_on` | outputs | list of input names | `<ModelStructure>` dependencies of the output. Without it, the output may depend on every input. |

Constructor and call arguments named by `init:`, `arg:` and `[time]` must exist in the signature (unless it accepts `**kwargs`).

---

## `[clocks.<name>]` (FMI 3)

One table per clock; `<name>` is the FMU clock name. See [fmi.md](fmi.md#clocks-fmi-3) for how clocks behave at runtime.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `causality` | `"input"` or `"output"` | `"input"` | Input: the importer ticks it. Output: the model ticks it. |
| `interval_variability` | string | `"constant"` with `interval`, else `"triggered"` | `constant`, `fixed`, `tunable` (periodic: need `interval`), `changing`, `countdown` (need `interval_from`), `triggered` (aperiodic). Output clocks must be `triggered`. |
| `interval` | number (s) | none | Periodic input clocks: the interval. |
| `shift` | number (s) | `0.0` | Periodic input clocks: offset of the first tick. |
| `interval_from` | `"attr:..."` / `"return..."` | none | `changing`/`countdown`: where the model's next interval is read after each tick. |
| `call` | string | none | Input clocks: what runs on a tick. A method name (classes), a function in the entry's module (functions), or `"module:function"`. Required if the clock has clocked inputs. |
| `from` | `"attr:..."` / `"return..."` | **required** for output clocks | The value that ticks the clock when it is true after a step or tick. |
| `description` | string | none | Clock description. |

---

## `[events]` (FMI 3)

| Key | Value | Meaning |
|---|---|---|
| `terminate` | `"attr:..."` / `"return..."` | When true after a step or tick, the FMU returns `terminateSimulation = true`. |
| `next_event_time` | `"attr:..."` / `"return..."` | Reported by `fmi3UpdateDiscreteStates` as the time of the next event. |

`[events]` is ignored, with a note, when building FMI 2.

---

## How the config maps onto `modelDescription.xml`

| Config | FMI 2 XML | FMI 3 XML |
|---|---|---|
| `[model] name / description / author` | `modelName / description / author` | same |
| — | `guid` | `instantiationToken` |
| `[experiment]` | `<DefaultExperiment>` | same |
| `fixed_step` | `canHandleVariableCommunicationStepSize` | same |
| build probe: can the model be pickled? | `canGetAndSetFMUstate`, `canSerializeFMUstate` | `canGetAndSetFMUState`, `canSerializeFMUState` |
| clocks or `[events]` | — | `hasEventMode="true"` |
| each variable | `<ScalarVariable>` + `<Real>`/`<Integer>`/... child with start, unit, min, max, nominal, quantity | `<Float64>`/`<Int32>`/`<Binary>`/... element with the same attributes; String and Binary starts as `<Start value=…/>` |
| `dimensions` | — | `<Dimension start=…/>` or `<Dimension valueReference=…/>` |
| `clocks` on a variable | — | `clocks="<clock valueReference>"` |
| `[clocks.<name>]` | — | `<Clock causality intervalVariability intervalDecimal shiftDecimal/>` |
| — | — | `<Float64 name="time" causality="independent"/>` |
| `unit` values | `<UnitDefinitions>` | same |
| `items` / `enum` | `<TypeDefinitions><SimpleType><Enumeration>` | `<TypeDefinitions><EnumerationType>` |
| outputs, `depends_on` | `<ModelStructure><Outputs>` | `<ModelStructure><Output>`, including output clocks |
| unclocked outputs without `start`, calculated parameters | `<InitialUnknowns>` | `<InitialUnknown>` |
