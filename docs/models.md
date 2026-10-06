# Writing models

fmugen packages Python code **as it is**. Nothing in your model has to import fmugen, follow a naming convention, or declare its interface. All of that lives in `fmugen.toml` (see [config.md](config.md)), and `fmugen init` writes a first version of it for you.

This page shows the shapes of code fmugen understands, how each maps onto an FMU, and what to check after `fmugen init`. [tested-models.md](tested-models.md) lists the published models fmugen has been tried on, and what each needed. Everything works for FMI 2 and FMI 3; the sections marked **FMI 3** need `[model] fmi_version = 3` (or `fmugen build --fmi 3`).

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
- [Libraries that need setup first](#libraries-that-need-setup-first)
- [Positional-only arguments](#positional-only-arguments)
- [Setter methods and properties](#setter-methods-and-properties)
- [Constructors that do the work](#constructors-that-do-the-work)
- [Arrays and structural parameters (FMI 3)](#arrays-and-structural-parameters-fmi-3)
- [Clocks (FMI 3)](#clocks-fmi-3)
- [Stopping the simulation from the model (FMI 3)](#stopping-the-simulation-from-the-model-fmi-3)
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
| a pandas Series, a one-row DataFrame, an xarray Dataset | `"return:<label>"` (index label, column, data variable) |
| something nested | a dotted path: `"return:zone.T"`, `"return:4.rewards.speed"`. Each step is a dict key, a tuple/list position or an attribute. |

Values nested in dicts, NamedTuples, dataclasses and `SimpleNamespace`s become outputs named with dots: `{"zone": {"T": 21}}` gives the output `"zone.T"` (quoted in TOML). `init` finds them in dict literals in the code, and with `--probe` in the actual result (up to 4 levels deep).

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

### Objects built from their fields

An argument that is a dataclass, a pydantic model or an attrs class (by its default, or by its annotation when it has no default) becomes one variable per field. For example, pythermalcomfort's `sports_heat_stress_risk(tdb, tr, rh, vr, sport: _SportsValues)`:

```toml
[inputs]
sport_clo = { start = 0.37, to = "arg:sport.clo" }
sport_met = { start = 7.5, to = "arg:sport.met" }
```

Before each call, fmugen builds `_SportsValues(clo=..., met=..., ...)`. With a default instance, it copies the default with these fields replaced, so fields that aren't FMI values keep their values. Give starts for fields without a default with `init --start sport.clo=0.37`. An argument that defaults to `None` stays a constant: `None` usually means "not given".

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

Some module names are already taken by UniFMU's backend and fmugen: `model`, `backend`, `main`, `abstract_backend`, `schemas` and `fmugen_runtime`. Your entry module can't use them; rename the file.

---

## Models from PyPI

The entry can be an installed module instead of a file:

```toml
[model]
entry = "simple_pid:PID"
requirements = ["simple-pid==2.0.1"]
```

`requirements` go into the FMU's `resources/requirements.txt`. They must be installed in the environment fmugen runs in, which is also the one the FMU runs with. See [packaging.md](packaging.md#the-fmus-python-environment).

---

## Libraries that need setup first

Some libraries must be configured before their functions work: `psychrolib.SetUnitSystem(psychrolib.SI)`, or `env.reset()` before a gym environment can step. List those calls in `[model] setup`:

```toml
[model]
entry = "psychrolib:GetHumRatioFromRelHum"
setup = ["psychrolib:SetUnitSystem(psychrolib.SI)"]
```

```toml
[model]
entry = "gymnasium.envs.classic_control.cartpole:CartPoleEnv"
call = "step"
setup = ["reset"]
```

A `"module:function(...)"` runs before the model is constructed; a bare `"method"` runs on the object right after construction. Arguments are Python literals or dotted names of importable objects (`psychrolib.SI`). The calls run every time the FMU initializes, so a reset FMU is set up again.

---

## Positional-only arguments

C extensions often accept arguments by position only, e.g. CoolProp's `PropsSI(output, name1, value1, name2, value2, fluid)`. Bind each one with `to = "pos:N"`:

```toml
[model]
entry = "CoolProp.CoolProp:PropsSI"

[inputs]
output = { start = "T",      to = "pos:0" }
name1  = { start = "P",      to = "pos:1" }
value1 = { start = 101325.0, to = "pos:2" }
name2  = { start = "Q",      to = "pos:3" }
value2 = { start = 0.0,      to = "pos:4" }
fluid  = { start = "Water",  to = "pos:5" }

[outputs]
value = { from = "return" }    # saturation temperature of water at 1 atm: 373.12 K
```

`fmugen init` binds positional-only arguments it can see this way. If a signature can't be inspected at all, as with `PropsSI`, `init` says so and you write the variables by hand.

---

## Setter methods and properties

Hardware-style APIs often set inputs through methods and expose readings as properties. For example, `tclab.TCLabModel` sets the heater with `lab.Q1(50)` and reads a sensor with `lab.T1`. Bind an input to a setter method with `to = "call:<method>"`; read a property like any attribute:

```toml
[model]
entry = "tclab:TCLabModel"
call = "update"

[model.constants]
synced = false                  # don't wait for real time

[time]
t = "time"

[inputs]
Q1 = { start = 50.0, unit = "%", to = "call:Q1" }   # lab.Q1(value) before every step

[outputs]
T1 = { unit = "degC" }                               # the T1 property after every step
```

`fmugen init` lists readable properties as outputs.

---

## Constructors that do the work

Some classes compute everything in `__init__`. For example, `iapws.IAPWS97(T=400, P=1)` is the water/steam state at those conditions, with every property as an attribute. `[model] kind = "function"` treats such a class like a function: it is constructed with the current inputs on every step, and outputs are read from the new object:

```toml
[model]
entry = "iapws:IAPWS97"
kind = "function"

[inputs]
T = { start = 400.0, unit = "K" }
P = { start = 1.0, unit = "MPa" }     # passed to IAPWS97(**kwargs)

[outputs]
h   = { from = "return:h", unit = "kJ/kg" }
rho = { from = "return:rho", unit = "kg/m3" }
```

---

## Arrays and structural parameters (FMI 3)

Give a variable `dimensions`, and your code exchanges lists or numpy arrays with the FMU. In FMI 3 the FMU has real array variables. FMI 2 has none, so the FMU gets one scalar per element (`q[1]` … `q[4]`), while the model still gets the whole array. Structural parameters (resizable arrays) need FMI 3.

```python
class KalmanFilter:                       # filterpy, unchanged
    def __init__(self, dim_x, dim_z): ...
    def predict(self): ...                # uses self.F, self.Q
    def update(self, z): ...
```

```toml
[structural_parameters]                   # sizes, set before initialization
dim_x = { start = 2 }
dim_z = { start = 1 }

[parameters]
F = { dimensions = ["dim_x", "dim_x"], numpy = true, to = "attr:F", start = [1.0, 0.1, 0.0, 1.0] }

[outputs]
x = { dimensions = ["dim_x"] }            # self.x, shape (2, 1) or (2,): any shape with 2 values
```

- **Sizes:** a dimension is a number (`[3]`) or a structural parameter (`["dim_x"]`). Structural parameters are FMU variables an importer can change in configuration mode, before initialization. Arrays that use them are resized to their start values.
- **Values:** arrays travel flattened in row-major order. `start` is a flat list, or one value for every element.
- **What your code sees:** nested lists, or a `numpy.ndarray` with `numpy = true`. Your code can return lists, tuples or numpy arrays of any shape with the right number of values.
- **Attribute bindings:** `to = "attr:F"` writes the array onto the object after construction and before every step. Use it for matrices the model reads, not for state the model updates itself.

`fmugen init --fmi 3` infers arrays from list, tuple and numpy defaults and results, and `Binary` from `bytes`.

Full example: [examples/kalman](../examples/kalman).

---

## Clocks (FMI 3)

FMI 3 clocks run code **on events** instead of on every step: sampled-data controllers, sensors that report when they have data, models that raise alarms. Your code stays the same; the config says which method a clock calls.

**A periodic input clock**, ticked by the importer every 0.1 s:

```toml
[model]
entry = "simple_pid:PID"
call = false                         # nothing runs on doStep: only the clock runs the PID

[clocks.sample]
interval = 0.1
call = "__call__"                    # pid(input_, dt) on every tick

[time]
dt = "step_size"                     # in a clock call: time since the last tick

[inputs]
measurement = { to = "arg:input_", clocks = ["sample"] }   # passed to the clock's call

[outputs]
output = { from = "return", clocks = ["sample"] }         # read after each tick, held in between
```

**A triggered input clock**, ticked whenever the importer has a measurement:

```toml
[clocks.measurement]                 # no interval: triggered
call = "update"                      # kf.update(z)

[inputs]
z = { dimensions = ["dim_z"], numpy = true, clocks = ["measurement"] }
```

**An output clock**, ticked by the model when a value it computes becomes true:

```python
class Tank:
    def fill(self, inflow, dt):
        self.level += inflow * dt
        self.overflowed = self.level > self.capacity
```

```toml
[clocks.overflow]
causality = "output"
from = "attr:overflowed"             # true after a step -> the clock ticks

[outputs]
spill = { from = "attr:level", clocks = ["overflow"] }
```

After a step that ticks an output clock, `doStep` returns `eventHandlingNeeded`. The importer enters event mode and sees the clock active.

What each interval variability means, and the exact rules for activation and reset: [fmi.md](fmi.md#clocks-fmi-3). Clocks can't be inferred; `fmugen init --fmi 3` writes a commented example.

Full examples: [examples/sampled_pid](../examples/sampled_pid), [examples/kalman](../examples/kalman).

---

## Stopping the simulation from the model (FMI 3)

If your model knows when the simulation should end, point `[events] terminate` at that value:

```toml
[events]
terminate = "attr:done"          # or "return:done" for a returned dict
```

When it is true after a step or a clock tick, the FMU returns `terminateSimulation = true` and the importer stops. `next_event_time = "attr:..."` reports when the model's next event is due.

---

## Logging and errors

- **Logging:** use Python's `logging` as usual. While your code runs inside the FMU, its records are forwarded to the importer:

  | Python level | FMI status | Log category |
  |---|---|---|
  | `WARNING` | warning | `logStatusWarning` |
  | `ERROR` and above | error | `logStatusError` |
  | everything else | OK | `logAll` (FMI 2) / `logEvents` (FMI 3) |

- **Errors:** an exception in your code makes that FMI call return an error status. The full traceback is logged under `logStatusError`.
- **`print`:** output goes to the backend process's console, not to the importer.

---

## What `fmugen init` infers

```bash
fmugen init path/to/model.py[:Name] [--call METHOD] [--fmi 3] [--start NAME=VALUE ...] [--setup CALL ...] [--kind function] [--probe] [--convert NAME=module:function ...] [-o fmugen.toml | -o -] [--force]
```

It imports the module, picks the entry, reads the signatures and **the source code**, and writes a commented config. **It does not call the model**: no object is built, no setup call or step is run. Models that need a device, a network or a licence can be configured anywhere. (Importing the module runs its top-level code, as any import does.)

Reading the code is enough for most plain-Python models. On the published models in [tested-models.md](tested-models.md), it gives the same outputs as calling the model for all 11 scalar functions (pvlib, fluids, ht, chemicals, iapws, psychrolib) and for the RC building. What it can't know, the config says in comments: array sizes (FMI 3), results built at runtime, code without Python source (C extensions), unannotated properties, and whether the object can be pickled (`save_state`).

**`--probe`** also calls the model once with the start values (setup calls, construction, one step), and fills in exactly those. Use it for ML models, C extensions and anything with array results. The probe only works if the model accepts the start values: arguments without a default start at `0`, which many models reject (`Re=0`, `dim=0`, a time step of 0).

| Option | Use |
|---|---|
| `--start NAME=VALUE` | A realistic start value (a Python literal; a list for an array), also used by `--probe`. Repeatable. |
| `--setup CALL` | A [setup call](#libraries-that-need-setup-first), written to the config; with `--probe`, also run before the probe. Repeatable. |
| `--kind function` | For [constructors that do the work](#constructors-that-do-the-work). |
| `--probe` | Call the model once to find what the code doesn't show. |
| `--convert NAME=module:function` | How an argument is passed in (`x=torch:tensor`, `x=numpy`, `x=pint`), when it isn't annotated. `pint` also needs a `unit` on the variable. |

```bash
fmugen init fluids.friction:friction_factor --start Re=1e5 -o -
```

```bash
fmugen init psychrolib:GetHumRatioFromRelHum --setup "psychrolib:SetUnitSystem(psychrolib.SI)" --start TDryBulb=25.0 --start RelHum=0.5 --start Pressure=101325.0 -o -
```

A `--start` name that appears in both the constructor and the step method goes to the one without a default; on a tie, to the step method. Names that neither declares are passed through `**kwargs`, if one of them accepts it.

| | Inferred from |
|---|---|
| **Entry** | The name after `:`, else the only public function or class defined in the module |
| **Inputs (functions) / parameters (classes)** | Arguments with a `bool`/`int`/`float`/`str` default, or with no default |
| **Start values and types** | The default value. With no default: the annotation, otherwise Real `0.0` |
| **Time arguments** | Arguments named `dt`, `step_size`, `h` (step size) or `t`, `time` (time) |
| **Outputs from the return value** | The code: dict keys (also a dict built in a variable), tuple positions, a single value (`y`), NamedTuple/dataclass fields, or the return annotation. With `--probe`: the actual result |
| **Outputs and locals of classes** | Public attributes the step method assigns, following the methods it calls on `self` (also assigned in `__init__`: local; else output), and annotated properties. With `--probe`: also what the step actually created or changed, and every readable numeric property |
| **States** | An input `x_prev` whose next value is returned or stored as `x_next` or `x` |
| **Sources** | Local modules under the config's folder that the model imported |
| **Constants** | Non-FMI defaults, written as commented-out examples |
| **Positional-only arguments** | Bound with [`to = "pos:N"`](#positional-only-arguments) |
| **Arrays and Binary** (`--fmi 3`) | List, tuple and numpy defaults and results become `dimensions` (`numpy = true` for numpy inputs); `bytes` becomes Binary; numpy `float32` becomes Float32 |

Check afterwards:

- **Start values:** arguments without a default get `0.0` unless you pass `--start`; make sure the model is valid there.
- **States:** only inputs named `x_prev` are detected. A model that takes its own previous result under another name (Madgwick's `updateIMU(q, ...)` returning the new `q`) needs a `[states]` entry: `q = { dimensions = [4], start = [1.0, 0.0, 0.0, 0.0], next = "return" }`.
- **Integer vs Real:** an `int` default (`setpoint=0`) gives an Integer. Write `0.0` for a Real.
- **Units and descriptions:** add them; they can't be inferred.
- **Outputs and locals:** remove the ones you don't need. Types come from annotations and obvious literals (`True`, comparisons, strings); everything else is Real. Uncomment and complete the commented lines (`dimensions = [...]`, properties, `save_state`), or rerun with `--probe`.
- **Tunable parameters:** `init` only suggests them in comments (see [above](#a-class-with-a-step-method)).

`fmugen build model.py` runs the same inference in memory. That's handy for a quick try; for anything you keep, write the config.

---

## Limits

- **Values:** FMI 2 has one value per variable, so fmugen writes an array as one scalar per element (`x[1]`, `x[2]`, …); its size must be fixed. FMI 3 has arrays, also resizable ones. In both versions, callables and objects can't be variables (use `constants`).
- **Clocks:** each clocked variable belongs to exactly one clock.
- **FMU state:** saving and restoring FMU state pickles your object (`cloudpickle` if `pickle` can't). If it holds something that can't be pickled (an ONNX session, an open file, a socket, a generator), `init` writes `save_state` with the attributes that can be saved, or `false`, and a comment saying what was left out. Check it: an attribute left out must not change during a simulation.
- **Derivatives:** the FMU can't provide them (directional derivatives, input/output derivatives). See [fmi.md](fmi.md#unsupported-functions).
