# UniFMU: bugs and limitations

Problems that come from [UniFMU](https://github.com/INTO-CPS-Association/unifmu) **0.14.0** (the version fmugen requires), not from fmugen. Each entry says where it was found, its effect on fmugen FMUs, and the workaround, if any. Sources: fmugen's own testing ([tested-models.md](tested-models.md), [tested-models-round2.md](tested-models-round2.md), [AUDIT.md](../AUDIT.md)) and the [UniFMU README](https://github.com/INTO-CPS-Association/unifmu/blob/master/README.md).

| # | Problem | Kind | Workaround in fmugen |
|---|---|---|---|
| 1 | [The importer hangs when the model prints more than ~4 KB](#1-the-importer-hangs-when-the-model-prints-more-than-4-kb) | Bug | `build --capture-output` |
| 2 | [The backend keeps running after an FMU error](#2-the-backend-keeps-running-after-an-fmu-error) | Bug | None. Send the importer's output to a file, not a pipe |
| 3 | [Error messages are lost when logging is off](#3-error-messages-are-lost-when-logging-is-off) | Limitation | None. Turn on debug logging in the importer |
| 4 | [Log messages only during an FMI call](#4-log-messages-only-during-an-fmi-call) | Limitation | None |
| 5 | [Unsupported FMI functions stop the backend](#5-unsupported-fmi-functions-stop-the-backend) | Limitation | Never declared, so compliant importers don't call them |
| 6 | [Co-Simulation only](#6-co-simulation-only) | Limitation | None |
| 7 | [Exact `protobuf==5.27.3` pin](#7-exact-protobuf-5273-pin) | Limitation | None |
| 8 | [The FMU needs a Python interpreter](#8-the-fmu-needs-a-python-interpreter) | Limitation | `--vendor`, `--compile` |
| 9 | [Reserved module names](#9-reserved-module-names) | Limitation | None. Rename the model file |
| 10 | [FMI 3 template declares `fmiVersion="3.0-beta.4"`](#10-fmi-3-template-declares-fmiversion30-beta4) | Bug | fmugen writes its own `modelDescription.xml` |
| 11 | [Smaller limitations from the README](#11-smaller-limitations-from-the-readme) | Limitation | — |
| 12 | [Unconfirmed: FMI 2 crash with FMPy debug logging](#12-unconfirmed-fmi-2-crash-with-fmpy-debug-logging) | Unconfirmed | — |

---

## 1. The importer hangs when the model prints more than ~4 KB

When the FMU's Python process writes more than about 4 KB in total to stdout/stderr, UniFMU's native library panics (`zeromq-0.4.1/src/rep.rs:168:40: not yet implemented`) and the importer waits forever, with no error.

- 3,900 characters printed: fine. 4,200: crash. Small flushed writes still crash, so it is the total amount.
- Large messages are not the cause: a 160 KB array output and a 70,000-character log message through the FMI logger both work.
- Typical triggers: library warnings, progress bars (Hugging Face model loading), printed tracebacks.

Found with Chronos-Bolt ([tested-models.md](tested-models.md), [AUDIT.md §5.7](../AUDIT.md)).

**Workaround:** `fmugen build --capture-output` redirects file descriptors 1 and 2 inside the backend to a temporary file, and sends the text to the importer's log as `[output]` messages after each call. Not reported upstream yet.

## 2. The backend keeps running after an FMU error

When an FMU call fails (an error status from `exitInitializationMode` or `doStep`), the importer exits, but UniFMU's Python backend stays alive: 2 processes (`venv\Scripts\python.exe main.py` and the base `python.exe main.py`). Successful runs leave nothing behind. Seen with FMI 2 and FMI 3, on Windows with FMPy.

Effects:
- The orphaned backend holds the importer's stdout/stderr. Anything that reads them through a pipe (`subprocess.run(capture_output=True)`, `fmpy simulate x.fmu | grep …`) waits forever.
- The orphans pile up: 31 pairs in the first round-2 run, 14 in the rerun. One held a lock on the FMU's work folder until killed.

Probably `fmi2FreeInstance` / `fmi3FreeInstance` isn't reached, or doesn't stop the backend, after an error status.

Found in [tested-models-round2.md](tested-models-round2.md) (problem 1). Reproduce: `fmpy simulate failing.fmu 2>&1 | Out-Null` in PowerShell never returns, and the count of `main.py` processes goes up by 2.

**Workaround:** send the importer's output to a file, not a pipe, and kill leftover `main.py` processes.

## 3. Error messages are lost when logging is off

fmugen sends the full Python traceback of a failure to the FMI log (`logStatusError`). UniFMU drops log messages when the importer instantiates the FMU with `loggingOn=False`, which `fmpy simulate` does, even with `--fmi-logging`. The user then sees only `fmi3ExitInitializationMode failed with status 3`, with no reason.

Found in [tested-models-round2.md](tested-models-round2.md) (problem 7).

**Workaround:** turn on debug logging in the importer, e.g. `fmpy.simulate_fmu(…, debug_logging=True, logger=print)`.

## 4. Log messages only during an FMI call

UniFMU can carry a log message to the importer only while it processes a command. Log records from the model's background threads between calls aren't forwarded. See [fmi.md](fmi.md#logging).

## 5. Unsupported FMI functions stop the backend

If an importer calls a function the Python backend doesn't implement (anything marked x in the [support overview](fmi.md#support-overview)), the backend stops with "unrecognized command" and the simulation fails, instead of the call returning an error status. fmugen never declares these capabilities in `modelDescription.xml`, so a compliant importer won't call them. See [fmi.md](fmi.md#unsupported-functions).

## 6. Co-Simulation only

The Python backend implements Co-Simulation only (UniFMU README, "Supported Features"):

- **No Model Exchange** (FMI 2 or 3), so an ODE model can't be integrated by the importer's own solver. This is the capability users will ask for most ([AUDIT.md §5.6, §8](../AUDIT.md)).
- **No Scheduled Execution** (FMI 3).
- **No directional or adjoint derivatives**, no input/output derivatives (`fmi2SetRealInputDerivatives`, `fmi2GetRealOutputDerivatives`, `fmi3GetOutputDerivatives`).
- **No asynchronous steps or status queries**: `fmi2CancelStep`, `fmi2Get*Status`.
- **No runtime variable dependencies**: `fmi3GetNumberOfVariableDependencies`, `fmi3GetVariableDependencies`. fmugen declares them statically in `<ModelStructure>`.
- **No `fmi3EvaluateDiscreteStates`.**
- **No intermediate update or early return** (FMI 3).
- **No FMI 1.**

## 7. Exact `protobuf==5.27.3` pin

The backend's generated `*_pb2.py` files require exactly `protobuf==5.27.3` (plus `pyzmq`). Since the FMU runs with the model's own environment, this pin lands there and can conflict with packages that pin protobuf differently (TensorFlow, grpcio, …). Regenerating the schemas, or testing a range like `protobuf>=5.27,<6`, would loosen it ([AUDIT.md](../AUDIT.md)).

## 8. The FMU needs a Python interpreter

UniFMU starts the backend with the command in `launch.toml`, so a Python FMU needs an interpreter and its packages on the target machine (`needsExecutionTool = true`). The README suggests bundling an interpreter yourself. fmugen offers `build --vendor` (wheels in the FMU, still needs Python) and `build --compile pyinstaller|nuitka` (no Python needed, but only runs on the OS it was built on). See [packaging.md](packaging.md).

The backend also uses `match`, so it needs **Python 3.10 or newer** ([AUDIT.md](../AUDIT.md)).

## 9. Reserved module names

The backend's own modules live in the FMU's `resources/` folder next to the model: `model`, `backend`, `main`, `abstract_backend` and `schemas` (plus fmugen's `fmugen_runtime`). A model whose entry module has one of these names can't be used; rename the file. See [models.md](models.md).

## 10. FMI 3 template declares `fmiVersion="3.0-beta.4"`

UniFMU 0.14 writes `fmiVersion="3.0-beta.4"` into the FMI 3 template's `modelDescription.xml`, not `3.0`. fmugen replaces that file on every build, so fmugen FMUs aren't affected ([packaging.md](packaging.md#unifmu-version)).

## 11. Smaller limitations from the README

- **`launch.toml` commands run without a shell**, so wildcards, per-session environment variables and aliases don't work. To use a shell, give it as the first element of the command.
- **Distributed FMUs (`generate-distributed`) are FMI 2 only**, per the README. fmugen doesn't use them yet.
- **Building UniFMU itself** pins Protocol Buffers v27.3 (the source of the pin in 7), and on Windows, git's CRLF line endings break the Docker build's bash scripts.

## 12. Unconfirmed: FMI 2 crash with FMPy debug logging

In the round-2 rerun, the FMI 2 FMU for `joblib:load` + `julien-c/skops-digits` crashed FMPy with `OSError: access violation reading 0x…24F0` when simulated with `simulate_fmu(…, debug_logging=True, logger=…)`. Reproduced twice, and also without the FMU's String parameter. Plain `fmpy simulate` of the same FMU exits with code 0, and the FMI 3 version works with debug logging. Not yet narrowed down to UniFMU, FMPy or the FMU ([tested-models-round2.md](tested-models-round2.md#rerun-after-the-fixes-2026-10-07)).
