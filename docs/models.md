# Writing models

fmugen packages Python code **as it is**. Nothing in your model has to import fmugen, follow a naming convention, or declare its interface. All of that lives in `fmugen.toml` (see [config.md](config.md)), and `fmugen init` writes a first version of it for you.

This page shows the shapes of code fmugen understands, how each maps onto an FMU, and what to check after `fmugen init`.

- [How a model runs inside the FMU](#how-a-model-runs-inside-the-fmu)
- [A function](#a-function)
- [A class with a step method](#a-class-with-a-step-method)
- [Results stored as attributes](#results-stored-as-attributes)
- [State fed back between steps](#state-fed-back-between-steps)
- [Time and step size](#time-and-step-size)
- [Arguments that aren't FMI values](#arguments-that-arent-fmi-values)
- [Enumerations](#enumerations)
- [Several files](#several-files)
- [Models from PyPI](#models-from-pypi)
- [Logging and errors](#logging-and-errors)
- [What `fmugen init` infers](#what-fmugen-init-infers)
- [Limits](#limits)

---

## How a model runs inside the FMU

Your model is the **entry**: a function or a class.

| | Function | Class |
|---|---|---|
| **On initialization** | Called once with the start values to compute the initial outputs. This does not advance states. | Constructed with the parameters: `Model(**parameters)`. |
| **On each `doStep(t, h)`** | Called with the current inputs. | The step method is called: `obj.step(**inputs)`. |
| **Outputs** | Read from the return value. | Read from the return value and/or the object's attributes. |
| **Between steps** | Nothing is kept except declared states. | The object keeps its own state, as in plain Python. |

A step takes the inputs at time `t`. The outputs it produces are the values at `t + h`.

---

## A function

```python
def compute_balances_simplified(temp_1, vfr_5, vfr_8, vfr_13, temp_11):
    ...
    return {"mass_balance": m, "energy_balance": e}
```

```toml
[model]
entry = "psychrometry.py:compute_balances_simplified"

[inputs]
temp_1 = { start = 28.0, unit = "degC" }
vfr_5  = { start = 1.2,  unit = "m3/s" }
# ...

[outputs]
mass_balance   = { unit = "kg/s" }      # reads result["mass_balance"]
energy_balance = { unit = "W" }
```

- **Inputs:** every argument is an input by default. Move an argument to `[parameters]` if it should only be set before the simulation.
- **Outputs:** the function can return different kinds of value, and each output reads its part with `from`:

| Return value | `from` |
|---|---|
| a dict | `"return:<key>"`. This is the default, using the output's name as the key. |
| a tuple or list | `"return:0"`, `"return:1"`, … |
| a single number | `"return"` |
| an object or dataclass | `"return:<attribute>"` |

Full example: [examples/psychrometry](../examples/psychrometry).

---

## A class with a step method

```python
class PID:
    def __init__(self, Kp=1.0, Ki=0.0, Kd=0.0, setpoint=0, ...):
        ...
    def __call__(self, input_, dt=None):
        ...
        return output
```

```toml
[model]
entry = "simple_pid:PID"
# call = "__call__"   (the default when the class is callable; otherwise required)

[parameters]          # constructor arguments
Kp = { start = 2.0, variability = "tunable" }

[inputs]              # step-method arguments
measurement = { start = 0.0, to = "arg:input_" }

[outputs]
output = { from = "return" }
```

- **Parameters** are passed to the constructor once, when the FMU leaves initialization mode.
- **Tunable parameters:** a parameter marked `variability = "tunable"` can still change during the simulation. fmugen then writes the new value onto the object (`obj.Kp = value`). Only mark a parameter tunable if the step method reads that attribute. If the constructor only uses it to compute something else, changing the attribute later has no effect, so keep it fixed.
- **Step method:** `call` names it. The default is `__call__` when the class is callable. `fmugen init` also tries `step`, `do_step`, `update`, and the only public method.
- **Renaming:** `to = "arg:input_"` gives an argument a different FMU name.

Full example: [examples/simple_pid](../examples/simple_pid).

---

## Results stored as attributes

Many simulation classes return nothing and store their results on `self`:

```python
class Zone:
    def solve_energy(self, internal_gains, solar_gains, t_out, t_m_prev):
        ...
        self.t_air = ...
        self.heating_demand = ...
```

For a class, an output reads the attribute with its own name by default (`from = "attr:<name>"`). Dotted paths such as `attr:results.t_air` also work.

```toml
[outputs]
t_air          = { start = 20.0, unit = "degC" }   # start: value before the first step
heating_demand = { unit = "W" }

[locals]                                           # exposed for plotting, not as outputs
t_m = { unit = "degC" }

[calculated_parameters]                            # attributes derived in __init__
c_m = { unit = "J/K" }
```

Before the first step, an attribute that doesn't exist yet keeps its `start` value (0 if there is none).

---

## State fed back between steps

Some models expect the caller to pass back last step's value, for example `solve_energy(..., t_m_prev)` with the result stored in `self.t_m_next`. Declare that argument as a **state**:

```toml
[states]
t_m_prev = { start = 20.0, unit = "degC", next = "attr:t_m_next" }
```

- **Each step:** fmugen passes the current value of `t_m_prev`, then replaces it with whatever `next` points to.
- **Where `next` can point:** `"attr:<name>"` for classes, or `"return"` / `"return:<key>"` for functions and classes.
- **Initial value:** a state is an FMU `local` variable with `initial="exact"`. An importer can set its start value before initialization.

This also makes plain functions stateful:

```python
def integrate(u, x_prev=0.0, dt=1.0):
    return {"x_next": x_prev + u * dt}
```

```toml
[states]
x_prev = { start = 0.0, next = "return:x_next" }
[time]
dt = "step_size"
```

Classes that keep their state in `self` don't need `[states]`; the object itself is the state.

---

## Time and step size

`[time]` maps arguments of the step function or method to the FMU's clock:

```toml
[time]
dt = "step_size"   # h of doStep(t, h)
t  = "time"        # t: time at the start of the step
# t_end = "end_time"   (t + h)
```

- **Initialization:** the function (if `init_call` is on) gets `time = start time` and `step_size = [experiment] step_size`, or 0 when that isn't set.
- **Fixed step size:** if the model only works with one step size (for example, it hard-codes an hour), set `[experiment] fixed_step = true` and `step_size`. The FMU then reports `canHandleVariableCommunicationStepSize="false"` and rejects any other step size with an error.

---

## Arguments that aren't FMI values

FMI variables can only be Real, Integer, Boolean, String or Enumeration. For any other argument (a tuple, `None`, a class, a callable), either leave it out so your code's default is used, or give it a fixed value in `[model.constants]` (constructor or function) or `[model.call_constants]` (step method):

```toml
[model.constants]
output_limits = { python = "(-100.0, 100.0)" }          # a Python literal
sample_time   = { python = "None" }
heating_supply_system = { ref = "supply_system:HeatPumpAir" }   # an importable object
```

---

## Enumerations

An argument whose default is a Python `Enum` member becomes an FMI Enumeration. The FMU carries it as an Integer: 1 for the first member, 2 for the second, and so on. Your code receives and returns the `Enum` member itself:

```python
class Mode(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"

def valve(flow=1.0, mode=Mode.OPEN): ...
```

```toml
[inputs]
mode = { enum = "valve:Mode", start = "OPEN" }
```

Without a Python enum, use `items = ["off", "low", "high"]`. Your code then receives the integer.

---

## Several files

List the extra files or directories your model imports in `sources`. They are copied into the FMU with the same layout, relative to `fmugen.toml`:

```toml
[model]
entry = "rc_simulator/building_physics.py:Zone"
sources = ["rc_simulator"]
```

Both import styles work:
- **Package imports** (`from .supply import X`): used when the entry's directory has an `__init__.py`.
- **Flat imports** (`import supply_system`): the entry's own directory is always on `sys.path`.

`fmugen init` fills `sources` from the local modules the model actually imported.

Some module names are already taken by UniFMU's backend: `model`, `backend`, `main`, `abstract_backend` and `schemas`. Your entry module can't use them; rename the file.

---

## Models from PyPI

The entry can be an installed module instead of a file:

```toml
[model]
entry = "simple_pid:PID"
requirements = ["simple-pid==2.0.1"]
```

`requirements` go into the FMU's `resources/requirements.txt`. With `fmugen build --vendor`, they are installed inside the FMU so it doesn't depend on what is installed where it runs. See [packaging.md](packaging.md#requirements-and---vendor).

---

## Logging and errors

- **Logging:** use Python's `logging` as usual. While your code runs inside the FMU, its records are forwarded to the importer:

  | Python level | FMI status | Log category |
  |---|---|---|
  | `WARNING` | `fmi2Warning` | `logStatusWarning` |
  | `ERROR` and above | `fmi2Error` | `logStatusError` |
  | everything else | `fmi2OK` | `logAll` |

- **Errors:** an exception in your code makes that FMI call return `fmi2Error`. The full traceback is logged under `logStatusError`.
- **`print`:** output goes to the backend process's console, not to the importer.

---

## What `fmugen init` infers

```bash
uv run fmugen init path/to/model.py[:Name] [--call METHOD] [-o fmugen.toml | -o -] [--force]
```

It imports the module, picks the entry, makes one probe call with the start values, and writes a commented config:

| | Inferred from |
|---|---|
| **Entry** | The name after `:`, else the only public function or class defined in the module |
| **Inputs (functions) / parameters (classes)** | Arguments with a `bool`/`int`/`float`/`str` default, or with no default |
| **Start values and types** | The default value. With no default: the annotation, otherwise Real `0.0` |
| **Time arguments** | Arguments named `dt`, `step_size`, `h` (step size) or `t`, `time` (time) |
| **Outputs from the return value** | The probe result: dict keys, tuple positions, a single value (`y`), or object attributes |
| **Outputs and locals of classes** | Public numeric attributes the probe step *created* (outputs) or *changed* (locals) |
| **States** | An input `x_prev` whose next value is returned or stored as `x_next` or `x` |
| **Sources** | Local modules under the config's folder that the model imported |
| **Constants** | Non-FMI defaults, written as commented-out examples |

Check afterwards:

- **Start values:** arguments without a default get `0.0`, so make sure the model is valid there.
- **Integer vs Real:** an `int` default (`setpoint=0`) gives an Integer. Write `0.0` for a Real.
- **Units and descriptions:** add them; they can't be inferred.
- **Outputs and locals:** remove the ones you don't need. Attributes that were 0 in the probe show up as Real.
- **Tunable parameters:** `init` only suggests them in comments (see [above](#a-class-with-a-step-method)).

`fmugen build model.py` runs the same inference in memory. That's handy for a quick try; for anything you keep, write the config.

---

## Limits

- **Values:** one value per FMI variable. Arrays have to be split into scalar variables, and callables or objects can't be variables (use `constants`).
- **FMU state:** saving and restoring FMU state pickles your object. If it holds something that can't be pickled (an open file, a generator, a socket), the build detects it and turns `canGetAndSetFMUstate` off.
- **Derivatives:** the FMU can't provide them (directional derivatives, input/output derivatives). See [fmi.md](fmi.md#unsupported-fmi-2-functions).
