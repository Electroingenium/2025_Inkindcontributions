# `fmugen.toml` reference

`fmugen.toml` describes how an unmodified Python model becomes an FMU. It sits in the model's folder, and every path in it is relative to that folder. `fmugen init` writes a first version (see [models.md](models.md#what-fmugen-init-infers)). This page lists every key.

Unknown keys are rejected with an error, so typos don't go unnoticed.

```toml
[model]                     # what to call
[model.constants]           # fixed non-FMI arguments (constructor / function)
[model.call_constants]      # fixed non-FMI arguments (step method)
[experiment]                # default experiment and step-size capability
[time]                      # arguments that receive the FMU time / step size
[parameters]                # FMU variables, one inline table each ...
[calculated_parameters]
[inputs]
[states]
[outputs]
[locals]
```

---

## `[model]`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `entry` | string | **required** | `"path/file.py:Name"` (a file under this folder) or `"package.module:Name"` (an installed module). `Name` is a function or a class. |
| `call` | string | `"__call__"` if the class is callable | Classes only: the method run on each step. |
| `name` | string | the entry's name | `modelName` in `modelDescription.xml`. `fmugen build --name` overrides it. |
| `description` | string | first line of the entry's docstring, else the module's | `description` in `modelDescription.xml`. |
| `author` | string | `""` | `author` in `modelDescription.xml`. `fmugen build --author` overrides it. |
| `sources` | list of strings | `[]` | Extra files and directories to copy into the FMU, keeping their paths. A file entry is always copied. |
| `requirements` | list of strings | `[]` | pip requirement specifiers the model needs at runtime. See [packaging.md](packaging.md#requirements-and---vendor). |
| `init_call` | bool | `true` for functions, `false` for classes | Call the function or step method when leaving initialization mode, to compute the initial outputs. States are not advanced by this call. |
| `terminate` | string | none | Classes only: a method called on `fmi2Terminate` (for example `"close"`). |

### `[model.constants]` and `[model.call_constants]`

These are fixed keyword arguments that are not FMU variables, typically values that FMI can't represent.
- `constants` go to the constructor (classes) or to the function (functions).
- `call_constants` go to the step method (classes only).

| Value | Passed to the model as |
|---|---|
| a TOML string, number, bool, array or table | that value (an array becomes a list) |
| `{ python = "<literal>" }` | `ast.literal_eval(literal)`, e.g. `"None"`, `"(0, 100)"`, `"{'a': 1}"` |
| `{ ref = "module:attr.path" }` | the imported object, e.g. a class or function |

Every key must be an argument of the constructor, function or method (unless it accepts `**kwargs`).

---

## `[experiment]`

All keys are optional.

| Key | Type | Meaning |
|---|---|---|
| `start_time` | number | `DefaultExperiment startTime`; also the FMU's time before `fmi2SetupExperiment`. |
| `stop_time` | number | `DefaultExperiment stopTime`. |
| `step_size` | number | `DefaultExperiment stepSize`. Also used for the initialization call and the build probe (default 1.0). |
| `tolerance` | number | `DefaultExperiment tolerance`. |
| `fixed_step` | bool, default `false` | The model only works with `step_size`: writes `canHandleVariableCommunicationStepSize="false"`, and `fmi2DoStep` with any other step size returns `fmi2Error`. Requires `step_size`. |

---

## `[time]`

Each key is an argument of the step function or method; its value says what to pass:

| Value | Passed |
|---|---|
| `"time"` | `t`, the communication point at the start of the step |
| `"step_size"` | `h`, the communication step size |
| `"end_time"` | `t + h` |

```toml
[time]
dt = "step_size"
```

---

## Variables

Each variable is one line: `name = { key = value, ... }`. The name is the FMU variable name and must be a valid Python identifier. Variables get value references in this order: parameters, calculated parameters, inputs, states, outputs, locals.

| Section | FMI causality | Value flows | Default binding |
|---|---|---|---|
| `[parameters]` | `parameter` | importer → model | class: constructor argument `init:<name>`; function: `arg:<name>` |
| `[calculated_parameters]` | `calculatedParameter` | model → importer | `attr:<name>` (classes only) |
| `[inputs]` | `input` | importer → model | `arg:<name>` |
| `[states]` | `local`, `initial="exact"` | fed back each step | `arg:<name>`, plus the required `next` |
| `[outputs]` | `output` | model → importer | class: `attr:<name>`; function: `return:<name>` |
| `[locals]` | `local` | model → importer | as outputs |

### Keys for every variable

| Key | Type | Default | Meaning |
|---|---|---|---|
| `type` | string | from `start`; Enumeration if `items` or `enum` is given; else `Real` | `Real`, `Integer`, `Boolean`, `String` or `Enumeration`. |
| `start` | value | see below | Start value. An Enumeration takes an item name or a 1-based index. |
| `unit` | string | none | Real only. Added to `<UnitDefinitions>`; informational. |
| `description` | string | none | Variable description. |
| `quantity` | string | none | Physical quantity, e.g. `"ThermodynamicTemperature"`. |
| `min`, `max` | number | none | Real, Integer and Enumeration only. Declared range; not enforced by the adapter. |
| `nominal` | number | none | Real only. |
| `variability` | string | parameters: `fixed`; others: `continuous` for Real, `discrete` otherwise | parameters: `fixed`/`tunable`; inputs: `discrete`/`continuous`; outputs and locals: also `constant`. |
| `initial` | string | see below | Overrides the FMI `initial` attribute where FMI allows a choice. |
| `items` | list of strings | none | Enumeration items, numbered from 1. The model receives the integer. |
| `enum` | string | none | `"module:EnumClass"`: items are the enum's members, and the model receives and returns members. |

**Start values and `initial`:**
- **Parameters, inputs, states:** always have a start value. If you don't give one, it is 0 / `false` / `""` / the first item.
- **Outputs without `start`:** `initial="calculated"`. **With `start`:** `initial="exact"`, and the start value is reported until the model produces a value (e.g. before the first step).
- **Locals and calculated parameters without `start`:** `initial="calculated"`. **With `start`:** `initial="approx"`.

### Binding keys

| Key | Sections | Value | Meaning |
|---|---|---|---|
| `to` | parameters, inputs, states | `"init:<arg>"` | Constructor argument (classes). |
| | | `"arg:<arg>"` | Argument of the function or step method. |
| | | `"attr:<name>"` | Attribute set on the object before each step and after construction (classes). Dotted paths allowed. |
| `from` | outputs, locals, calculated_parameters | `"return"` | The whole return value. |
| | | `"return:<key>"` | `result[key]` for a dict, `result[int(key)]` for a tuple or list, else `result.key`. |
| | | `"attr:<name>"` | An attribute of the object after the step (classes). Dotted paths allowed. Calculated parameters must use this form. |
| `next` | states (**required**) | same forms as `from` | Where the state's value for the next step comes from. |
| `attr` | parameters | string or `false` | Tunable class parameters: the attribute written when the importer changes the value after initialization. Defaults to the parameter's `to` name. `false` means it is passed only to the constructor. |
| `depends_on` | outputs | list of input names | `<ModelStructure>` dependencies of the output. Without it, the output may depend on every input. |

Constructor and call arguments named by `init:`, `arg:` and `[time]` must exist in the signature (unless it accepts `**kwargs`).

---

## How the config maps onto `modelDescription.xml`

| Config | XML |
|---|---|
| `[model] name / description / author` | `fmiModelDescription modelName / description / author` |
| `[experiment]` | `<DefaultExperiment>` |
| `fixed_step` | `CoSimulation canHandleVariableCommunicationStepSize` |
| build probe: can the model be pickled? | `canGetAndSetFMUstate`, `canSerializeFMUstate` |
| each variable | `<ScalarVariable>` with causality, variability, initial, description, and a `<Real>`/`<Integer>`/... child with start, unit, min, max, nominal, quantity |
| `unit` values | `<UnitDefinitions>` |
| `items` / `enum` | `<TypeDefinitions><SimpleType><Enumeration>` |
| outputs, `depends_on` | `<ModelStructure><Outputs>` |
| outputs without `start`, calculated parameters | `<ModelStructure><InitialUnknowns>` |
