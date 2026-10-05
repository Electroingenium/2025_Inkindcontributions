# Tested models

fmugen has been tried on published, unmodified Python models: the examples in this repository, and 20 more models from 11 open-source projects on PyPI. Each was run through the whole pipeline for **FMI 2 and FMI 3**: `fmugen init` → `fmugen build` → `fmpy validate` → `fmpy simulate`.

- **Repository examples:** the 5 examples build, validate and simulate. The 3 that use no FMI 3-only features give identical results under FMI 2 and FMI 3.
- **PyPI models:** **37 of 40 runs pass** (20 models × 2 FMI versions). The 3 that fail are FMI 2 builds of models whose inputs are arrays, which only FMI 3 has. `init` stops them with a clear message.
- **A neural network:** Amazon's [Chronos-Bolt Tiny](#a-neural-network-chronos-bolt) forecaster (PyTorch, weights from Hugging Face) builds, validates and simulates under FMI 3. Its forecasts are identical to calling the model directly.

These runs are how the [`[model] setup`](models.md#libraries-that-need-setup-first), [`to = "pos:N"`](models.md#positional-only-arguments), [`to = "call:…"`](models.md#setter-methods-and-properties) and [`kind = "function"`](models.md#constructors-that-do-the-work) features, and `init --start/--setup/--kind`, came about. Chronos-Bolt led to `[model] create` / `init --create`, `convert`, tensor outputs and `build --capture-output`.

- [Projects](#projects)
- [Repository examples](#repository-examples)
- [Models from PyPI](#models-from-pypi)
- [A neural network: Chronos-Bolt](#a-neural-network-chronos-bolt)
- [What was checked](#what-was-checked)
- [Reproducing a run](#reproducing-a-run)

---

## Projects

| Project | Version | License | Used for |
|---|---|---|---|
| Psychrometry model (Lucia Royo-Pascual, EIUM) | — | — | [examples/psychrometry](../examples/psychrometry) |
| [simple-pid](https://github.com/m-lundberg/simple-pid) | 2.0.1 | MIT | [examples/simple_pid](../examples/simple_pid), [examples/sampled_pid](../examples/sampled_pid) |
| [RC_BuildingSimulator](https://github.com/architecture-building-systems/RC_BuildingSimulator) | commit `97c1cdd` | MIT (amended) | [examples/rc_building](../examples/rc_building) |
| [FilterPy](https://github.com/rlabbe/filterpy) | 1.4.5 | MIT | [examples/kalman](../examples/kalman); `GHFilter`, `Q_discrete_white_noise` |
| [PsychroLib](https://github.com/psychrometrics/psychrolib) | 2.5.0 | MIT | `GetHumRatioFromRelHum` |
| [CoolProp](https://github.com/CoolProp/CoolProp) | 8.0.0 | MIT | `PropsSI` |
| [pvlib](https://github.com/pvlib/pvlib-python) | 0.16.1 | BSD-3-Clause | `pvwatts_dc`, `sapm_cell`, `alt2pres`, `aoi` |
| [fluids](https://github.com/CalebBell/fluids) | 1.3.1 | MIT | `friction_factor`, `Reynolds` |
| [ht](https://github.com/CalebBell/ht) | 1.2.0 | MIT | `Nu_conv_internal`, `effectiveness_from_NTU` |
| [chemicals](https://github.com/CalebBell/chemicals) | 1.5.2 | MIT | `Antoine` |
| [iapws](https://github.com/jjgomera/iapws) | 1.5.5 | GPL-3.0 | `_TSat_P`, `IAPWS97` |
| [AHRS](https://github.com/Mayitzin/ahrs) | 0.4.0 | MIT | `Madgwick`, `Mahony` |
| [Gymnasium](https://github.com/Farama-Foundation/Gymnasium) | 1.3.0 | MIT | `CartPoleEnv`, `PendulumEnv` |
| [TCLab](https://github.com/jckantor/TCLab) | 1.0.0 | Apache-2.0 | `TCLabModel` |
| [Chronos](https://github.com/amazon-science/chronos-forecasting) (`chronos-forecasting`, weights [`amazon/chronos-bolt-tiny`](https://huggingface.co/amazon/chronos-bolt-tiny)) | 2.3.2, with torch 2.14.1, transformers 5.18.0 | Apache-2.0 | `ChronosBoltPipeline` |

Only RC_BuildingSimulator is copied into this repository. The others are installed from PyPI when needed.

---

## Repository examples

| Example | Model shape | FMI 2 | FMI 3 |
|---|---|---|---|
| [psychrometry](../examples/psychrometry) | function returning a dict | ✓ | ✓ (same results) |
| [simple_pid](../examples/simple_pid) | class from PyPI, `__call__`, time step argument, tunable parameters | ✓ | ✓ (same results) |
| [rc_building](../examples/rc_building) | multi-file package, results as attributes, fed-back state, fixed step | ✓ | ✓ (same results) |
| [kalman](../examples/kalman) | arrays, structural parameters, triggered clock | — | ✓ |
| [sampled_pid](../examples/sampled_pid) | periodic clock, `call = false` | — | ✓ |

---

## Models from PyPI

Columns:
- **`init` options:** what was passed to `fmugen init` besides the target. "—" means nothing: the config was inferred from the code alone.
- **FMI 2 / FMI 3:** whether `build`, `validate` and `simulate` all passed.

| Model | Shape | `init` options | FMI 2 | FMI 3 |
|---|---|---|---|---|
| `pvlib.pvsystem:pvwatts_dc` | function | — | ✓ | ✓ |
| `pvlib.temperature:sapm_cell` | function | — | ✓ | ✓ |
| `pvlib.atmosphere:alt2pres` | function | — | ✓ | ✓ |
| `pvlib.irradiance:aoi` | function | — | ✓ | ✓ |
| `ht.hx:effectiveness_from_NTU` | function, string argument | — | ✓ | ✓ |
| `chemicals.vapor_pressure:Antoine` | function | — | ✓ | ✓ |
| `fluids.friction:friction_factor` | function | `--start Re=1e5` | ✓ | ✓ |
| `fluids.core:Reynolds` | function | `--start V=1.0 D=0.1 rho=1000.0 mu=0.001` | ✓ | ✓ |
| `ht.conv_internal:Nu_conv_internal` | function | `--start Re=1e4 Pr=0.7` | ✓ | ✓ |
| `iapws.iapws97:_TSat_P` | function | `--start P=1.0` | ✓ | ✓ |
| `filterpy.common:Q_discrete_white_noise` | function returning a matrix | `--start dim=2` | ✓ (no outputs: the result is an array) | ✓ (2×2 array output) |
| `psychrolib:GetHumRatioFromRelHum` | function, library setup | `--setup "psychrolib:SetUnitSystem(psychrolib.SI)"`, `--start TDryBulb=25.0 RelHum=0.5 Pressure=101325.0` | ✓ | ✓ |
| `CoolProp.CoolProp:PropsSI` | C extension, positional-only, strings | hand-written config ([shown here](models.md#positional-only-arguments)) | ✓ | ✓ |
| `iapws:IAPWS97` | constructor does the work, `**kwargs` | `--kind function --start T=400.0 P=1.0` | ✓ | ✓ |
| `filterpy.gh:GHFilter` | class, `update(z)`, argument names shared with the constructor | `--call update --start x=0.0 dx=1.0 dt=0.1 g=0.8 h=0.2` | ✓ | ✓ |
| `tclab:TCLabModel` | class, `update(t)`, properties, setter methods | — (heater input: [`to = "call:Q1"`](models.md#setter-methods-and-properties) by hand) | ✓ | ✓ |
| `gymnasium…cartpole:CartPoleEnv` | class, `step(action)`, setup, tuple result | `--call step --setup reset --start action=1` | ✓ (no observation output: it is an array) | ✓ |
| `gymnasium…pendulum:PendulumEnv` | class, array action, setup | `--fmi 3 --call step --setup reset --start "u=[0.5]"` | ✗ array input | ✓ |
| `ahrs.filters:Madgwick` | class, `updateIMU(q, gyr, acc)` arrays | `--fmi 3 --call updateIMU --start "q=[1.0, 0.0, 0.0, 0.0]" "gyr=[0.0, 0.0, 0.01]" "acc=[0.0, 0.0, 9.81]"` | ✗ array input | ✓ |
| `ahrs.filters:Mahony` | as Madgwick | as Madgwick | ✗ array input | ✓ |

Each `--start` takes one `NAME=VALUE`; the table groups several per row for brevity.

---

## A neural network: Chronos-Bolt

[Chronos-Bolt Tiny](https://huggingface.co/amazon/chronos-bolt-tiny) is a pretrained transformer (about 9 M parameters) that forecasts a time series from its recent history. It is used as published: `pip install chronos-forecasting` into a venv, plus fmugen.

| Model | Shape | `init` options | FMI 2 | FMI 3 |
|---|---|---|---|---|
| `chronos:ChronosBoltPipeline` | class built by a factory (`from_pretrained`), `predict(inputs)`, tensor in and out, weights downloaded from Hugging Face | `--fmi 3 --create from_pretrained --call predict --start pretrained_model_name_or_path=amazon/chronos-bolt-tiny --start "inputs=[…24 values…]"`; build with `--capture-output` | — (array input: FMI 3 only) | ✓ |

`init` inferred everything from the code and the start values:

```toml
[model]
entry = "chronos:ChronosBoltPipeline"
fmi_version = 3
create = "from_pretrained"
call = "predict"

[parameters]
pretrained_model_name_or_path = { start = "amazon/chronos-bolt-tiny" }

[inputs]
inputs = { dimensions = [24], start = [20.0, 21.294, …], convert = "torch:tensor" }   # from the torch.Tensor annotation
limit_prediction_length = { start = false }

[outputs]
y = { from = "return", dimensions = [1, 9, 64], type = "Float32" }   # 9 quantiles × 64 steps ahead
quantiles = { dimensions = [9] }                                     # a property: 0.1 … 0.9
```

What it took:

- **Factory construction.** The pipeline is created with `ChronosBoltPipeline.from_pretrained(name)`; its constructor takes an already-loaded network. [`[model] create`](config.md#model) names the classmethod, and its arguments become parameters, so the Hugging Face model name is a String parameter.
- **Tensors.** `predict` takes a `torch.Tensor`. `convert = "torch:tensor"` converts the FMU's array before the call; `init` sets it from the annotation. The returned tensor becomes a Float32 array output.
- **Console output.** Loading the model prints warnings and a progress bar. UniFMU 0.14 crashes when the FMU's Python prints more than about 4 KB, and the importer hangs. `build --capture-output` sends it to the importer's log instead.
- **A crash in `init` itself**, when cleaning up after `transformers`, whose modules import on attribute access. Fixed in fmugen.

Checked with FMPy (`FMU3Slave`), feeding 24 hourly values of a daily temperature cycle (20 ± 5 °C):

- `fmpy validate`: no problems.
- Two forecasts, from the cycle and from the cycle shifted by 6 h: the median forecast follows the cycle, with a mean absolute error over the next 24 h of 0.29 °C and 0.61 °C.
- The FMU's 128 forecast values are **identical** (difference 0.0) to calling `ChronosBoltPipeline.predict` directly.
- Saving and restoring the FMU state works.
- Instantiation and initialization take about 58 s (importing PyTorch and loading the network); each forecast step about 0.05 s.

Limits:

- The weights are downloaded from Hugging Face on first use and cached in the user's Hugging Face cache. They are not inside the FMU: an FMU built with `--vendor` or `--compile` still needs network access (or a filled cache) on the target the first time.
- `--vendor` and `--compile` were not tried with this model. PyTorch makes either one large (hundreds of MB).

---

## What was checked

Passing `fmpy validate` and `fmpy simulate` shows the FMU is well-formed and runs. In addition:

- **Spot values:** these were compared with reference values, and FMI 2 and FMI 3 gave the same numbers:

  | Model | Conditions | Result | Reference |
  |---|---|---|---|
  | PsychroLib | 25 °C, 50 % RH, 101325 Pa | humidity ratio 0.00988 kg/kg | psychrometric chart: ≈ 0.0099 |
  | CoolProp | water, 101325 Pa, Q = 0 | 373.12 K | normal boiling point of water |
  | iapws `_TSat_P` | 1 MPa | 453.04 K | steam tables: 179.9 °C |
  | iapws `IAPWS97` | 400 K, 1 MPa | h = 533.5 kJ/kg, ρ = 937.9 kg/m³ | liquid water at those conditions |
  | fluids `Reynolds` | V = 1 m/s, D = 0.1 m, ρ = 1000, μ = 0.001 | 1.0 × 10⁵ | ρVD/μ |
  | fluids `friction_factor` | Re = 10⁵, smooth pipe | 0.0180 | Moody chart |
  | ht `Nu_conv_internal` | Re = 10⁴, Pr = 0.7 | 30.3 | turbulent pipe-flow correlations |

- **Dynamic models over time:**
  - **TCLab:** at 50 % heater power, T1 rises from 21 °C to 50 °C in 10 minutes, and T2 warms to 26 °C through thermal coupling.
  - **Madgwick:** with `q` [fed back as a state](models.md#what-fmugen-init-infers), turning at 0.1 rad/s for 10 s gives q = [0.878, 0, 0, 0.478]. The analytic value is [0.878, 0, 0, 0.479].
  - **CartPole and Pendulum:** their observations evolve step by step.
  - **GH filter:** it tracks its input.
- **Results not checked:** the pvlib and chemicals runs used only the code defaults (zeros where there are none), so they show that the FMUs run, not that the numbers mean anything.

---

## Reproducing a run

1. Install the project's package in an environment together with the model's library.
2. Run `init` with the options from the table.
3. Build and check the FMU.

For example, for `fluids`:

```bash
fmugen init fluids.friction:friction_factor --start Re=1e5 -o -
```

Write the config with `-o path/to/fmugen.toml` instead of `-o -`, then:

```bash
fmugen build path/to/fmugen.toml -o out/friction.fmu
```

Add `--fmi 3` to `init` or `build` for FMI 3.

Run these from an environment with fmugen and `fluids` installed (`pip install fmugen fluids`). The FMU runs with that environment (see [packaging.md](packaging.md#the-fmus-python-environment)).
