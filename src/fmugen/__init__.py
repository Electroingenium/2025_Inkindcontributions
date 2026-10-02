"""Turn ordinary Python models into UniFMU (FMI 2.0 Co-Simulation) FMUs.

The model code is not changed. A sidecar fmugen.toml (written by `fmugen init`, or
inferred by `fmugen build model.py`) says which function or class to call and how
its arguments, return value and attributes map to FMU variables.
See README.md and docs/.
"""
