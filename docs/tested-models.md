# Tested models

fmugen has been tried on published, unmodified Python models: the examples in this repository, and 20 more models from 11 open-source projects on PyPI. Each was run through the whole pipeline for **FMI 2 and FMI 3**: `fmugen init` → `fmugen build` → `fmpy validate` → `fmpy simulate`.

- **Repository examples:** the 5 examples build, validate and simulate. The 3 that use no FMI 3-only features give identical results under FMI 2 and FMI 3.
- **PyPI models:** **37 of 40 runs pass** (20 models × 2 FMI versions). The 3 that fail are FMI 2 builds of models whose inputs are arrays, which only FMI 3 has. `init` stops them with a clear message.
- **Neural networks:** [6 small published networks](#neural-networks) (on PyTorch or ONNX Runtime: forecasters, a voice detector, a reinforcement-learning controller, a molecular energy model and a surrogate) build, validate and simulate. **Every result is identical** to calling the model directly.

These runs are how the [`[model] setup`](models.md#libraries-that-need-setup-first), [`to = "pos:N"`](models.md#positional-only-arguments), [`to = "call:…"`](models.md#setter-methods-and-properties) and [`kind = "function"`](models.md#constructors-that-do-the-work) features, and `init --start/--setup/--kind`, came about. The neural networks led to `[model] create` / `init --create`, `convert`, tensor outputs, `build --capture-output`, factory functions (a function entry with `call`), computed constants (`{ call = "…" }`), tuple and dict arguments (`to = "arg:NAME[i]"`), NamedTuple field names, 0-d array results, and `init` retrying array inputs as numpy arrays or tensors.

- [Projects](#projects)
- [Repository examples](#repository-examples)
- [Models from PyPI](#models-from-pypi)
- [Neural networks](#neural-networks)
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
| [Silero VAD](https://github.com/snakers4/silero-vad) (`silero-vad`) | 6.2.3, with onnxruntime 1.30.0 | MIT | `load_silero_vad` |
| [Granite TSFM](https://github.com/ibm-granite/granite-tsfm) (`granite-tsfm`, weights [`ibm-granite/granite-timeseries-ttm-r2`](https://huggingface.co/ibm-granite/granite-timeseries-ttm-r2)) | 0.3.10, with torch 2.11.0, transformers 5.18.0 | Apache-2.0 | `get_model` (TinyTimeMixer) |
| [Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3) + [huggingface_sb3](https://github.com/huggingface/huggingface_sb3) (model [`sb3/demo-hf-CartPole-v1`](https://huggingface.co/sb3/demo-hf-CartPole-v1)) | 2.9.0 / 3.0, with torch 2.14.1, gymnasium 1.4.0 | MIT / Apache-2.0 | `PPO` |
| [surfaces](https://github.com/SimonBlanke/Surfaces) (`surfaces[surrogates]`) | 0.9.0, with onnxruntime 1.30.0 | MIT | `GradientBoostingRegressorFunction` (ONNX surrogate) |
| [TorchANI](https://github.com/aiqm/torchani) | 2.9.0, with torch 2.13.0 | MIT | `ANI2x` |
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
- **`init` options:** what was passed to `fmugen init` besides the target. "—" means nothing else was needed.
- **FMI 2 / FMI 3:** whether `build`, `validate` and `simulate` all passed.

These runs were made while `init` always called the model, which is now `init --probe`. Rerun since then **without `--probe`** (the model is not called, only its code is read):

- The 11 scalar functions (pvlib ×4, `effectiveness_from_NTU`, `Antoine`, `friction_factor`, `Reynolds`, `Nu_conv_internal`, `_TSat_P`, `GetHumRatioFromRelHum`) give **exactly the same outputs** as with the probe.
- `IAPWS97` (`--kind function`): 29 of the 52 outputs are found in the code; the other 23 are set by a helper that fills the object in a loop, which only `--probe` sees. None found in the code is wrong.
- `TCLabModel`: its six properties (`T1`, `Q1`, …) have no type annotation, so they're written as commented lines to uncomment; `--probe` reads them.
- `PropsSI` is a C extension: no source to read, with or without the probe; its config is written by hand.
- Models with array results (Gymnasium, Madgwick) need `--probe` for the array sizes with FMI 3 (not rerun).

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
| `fluids.units:Reynolds` | function taking and returning pint quantities | hand-written: `convert = "pint"` and a `unit` on each input ([below](#what-was-checked)) | ✓ | ✓ |
| `fluids.units:head_from_P` | as `Reynolds`, dimensional output | as `Reynolds`, output `unit = "cm"` | — | ✓ |

Each `--start` takes one `NAME=VALUE`; the table groups several per row for brevity.

---

## Neural networks

Six small, published networks, each installed as published (`pip install <package>`) into its own venv together with fmugen, then run through `init --probe` → `build` → `fmpy validate` → simulation with FMPy (`FMU3Slave` / `FMU2Slave`). Each result was compared with calling the model directly in its own venv. Neural networks need `--probe`: their result sizes depend on the weights, and their code is mostly compiled or framework code. Rerun after `--probe` became opt-in, the Chronos, Silero VAD and TorchANI configs came out identical.

| Model | Size, runtime | Shape | `init` options | FMI 2 | FMI 3 |
|---|---|---|---|---|---|
| `chronos:ChronosBoltPipeline` | ~9 M params, PyTorch | classmethod factory, tensor in/out | [below](#chronos-bolt) | — (array input) | ✓ |
| `silero_vad:load_silero_vad` | ~2 MB, ONNX Runtime | **factory function**, recurrent state, unannotated tensor input | `--probe --fmi 3 --call __call__ --start onnx=true --start "x=[…512 samples…]" --start sr=16000`; build with `--capture-output` | — (array input) | ✓ |
| `tsfm_public.toolkit.get_model:get_model` | 805 k params, PyTorch | factory function with `**kwargs`, 3-D tensor input, Hugging Face output object | `--probe --fmi 3 --call forward --start model_path=ibm-granite/granite-timeseries-ttm-r2 --start context_length=512 --start prediction_length=96 --start "past_values=[[[…512 values…]]]"`; build with `--capture-output` | — (array input) | ✓ |
| `stable_baselines3:PPO` | 9 k params, PyTorch | classmethod factory whose argument is a **downloaded file**, tuple result with a 0-d action | `--probe --fmi 3 --create load --call predict --start "path=call:huggingface_sb3:load_from_hub(repo_id='sb3/demo-hf-CartPole-v1', filename='ppo-CartPole-v1.zip')" --start "observation=[0.0, 0.0, 0.05, 0.0]" --start deterministic=true`; build with `--capture-output` | — (array input) | ✓ |
| `surfaces…gradient_boosting_regressor:GradientBoostingRegressorFunction` | 19 KB MLP, ONNX Runtime | class, hyperparameters through `**kwargs` | `--probe --call __call__ --start use_surrogate=true --start n_estimators=78 --start max_depth=13` | ✓ | ✓ |
| `torchani.models:ANI2x` | 1.7 M params (one network), PyTorch | factory function, **tuple argument** `(species, coordinates)`, NamedTuple result | `--probe --fmi 3 --call forward --start model_index=0 --start "species_coordinates=([[6, 1, 1, 1, 1]], [[[0.0, 0.0, 0.0], …]])"`; build with `--capture-output` | — (array input) | ✓ |

What was checked:

| Model | Test | Result |
|---|---|---|
| Silero VAD | 40 chunks of 512 samples: noise, a voiced vowel-like sound (140 Hz harmonics, syllable envelope), noise | All 40 speech probabilities identical to the direct calls, so the recurrent state carries over between FMI steps. 0.09 → 0.01 on noise, 0.76–0.997 on the voiced sound, back to 0 after. 40 steps: 0.08 s. |
| Granite TTM | Two 96-hour forecasts from 512 hours of a daily cycle with weekly modulation | All 192 values identical. Mean absolute error 1.94 and 2.04 against the true series (amplitude ±25). Save/restore works. |
| SB3 PPO | **Closed loop of two FMUs:** the PPO policy FMU controls a Gymnasium `CartPoleEnv` FMU, exchanging observation and action every step | The pole stays up the full 500 steps (largest angle 0.045 rad; the episode fails at 0.209). All 500 actions identical to `PPO.predict`. |
| surfaces | A 4 × 4 grid of `n_estimators` × `max_depth`, FMI 2 and FMI 3 | All 16 predictions identical, for both FMI versions. |
| TorchANI | Methane with one C–H bond stretched from 0.85 to 1.60 Å | All 16 energies identical. Minimum at 1.10 Å (experiment: 1.09 Å); +39 kcal/mol compressed to 0.85 Å, +61 kcal/mol stretched to 1.60 Å. Save/restore works. |

Notes:

- **No model code was changed.** What the configs needed is now part of fmugen; see the features listed at the top of this page.
- **`--capture-output`** was needed whenever a model prints while loading (warnings, progress bars), which hangs UniFMU 0.14 otherwise ([manual](manual.md)).
- **State save/restore** for the two ONNX Runtime models: an `InferenceSession` can't be pickled. `init` now saves only the other attributes. For Silero VAD it writes `save_state = ["_state", "_context", "_last_sr", "_last_batch_size", "sample_rates"]`, leaving out the fixed `session`; a rollback through UniFMU (20 chunks, save, 10 chunks, restore, the same 10 again) gives identical probabilities. surfaces was not re-run after this change.
- **Weights from Hugging Face** (Chronos, TTM, PPO) are downloaded on first use into the user's cache, not put inside the FMU.

### Chronos-Bolt

[Chronos-Bolt Tiny](https://huggingface.co/amazon/chronos-bolt-tiny) is a pretrained transformer (about 9 M parameters) that forecasts a time series from its recent history. It is used as published: `pip install chronos-forecasting` into a venv, plus fmugen.

| Model | Shape | `init` options | FMI 2 | FMI 3 |
|---|---|---|---|---|
| `chronos:ChronosBoltPipeline` | class built by a factory (`from_pretrained`), `predict(inputs)`, tensor in and out, weights downloaded from Hugging Face | `--probe --fmi 3 --create from_pretrained --call predict --start pretrained_model_name_or_path=amazon/chronos-bolt-tiny --start "inputs=[…24 values…]"`; build with `--capture-output` | — (array input: FMI 3 only) | ✓ |

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
  | fluids.units `Reynolds` | V = 5 m/s, D = 0.25 m, ρ = 1.1613 kg/m³, μ = 1.9 × 10⁻⁵ Pa·s | 76401.3 | `fluids.units.Reynolds` called directly with the same quantities |
  | fluids.units `head_from_P` | P = 100 kPa, ρ = 1000 kg/m³, output in cm | 1019.7 cm | 10.197 m from `fluids.units` directly |

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
