"""fmugen runtime engine, shared by the FMI 2 and FMI 3 adapters (resources/model.py).

This file is identical for every model and every FMI version. It reads
resources/interface.json, imports the user's code (resources/fmugen_model/) and runs it: constructing the model
object, calling it once per step or per clock tick, and moving values between FMU
variables and the arguments, return values and attributes of the user's code.

The user's code is never modified. The FMI-version-specific adapters translate
FMI calls into the methods of `Engine`.
"""
import ast
import asyncio
import builtins
import contextlib
import copy
import dataclasses
import datetime
import importlib
import inspect
import json
import logging
import math
import os
import pickle
import random
import sys
import tempfile
import traceback
import types
import typing
import warnings
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path

# The interface.json format this runtime reads; fmugen build writes the same number
SPEC_VERSION = 1

DEFAULT_VALUES = {
    "Real": 0.0, "Float32": 0.0, "Float64": 0.0,
    "Integer": 0, "Int8": 0, "UInt8": 0, "Int16": 0, "UInt16": 0,
    "Int32": 0, "UInt32": 0, "Int64": 0, "UInt64": 0,
    "Boolean": False, "String": "", "Binary": b"", "Enumeration": 1,
}
INT_RANGES = {
    "Int8": (-2**7, 2**7 - 1), "UInt8": (0, 2**8 - 1),
    "Int16": (-2**15, 2**15 - 1), "UInt16": (0, 2**16 - 1),
    "Int32": (-2**31, 2**31 - 1), "UInt32": (0, 2**32 - 1),
    "Int64": (-2**63, 2**63 - 1), "UInt64": (0, 2**64 - 1),
    "Integer": (-2**31, 2**31 - 1),
}
FLOAT_TYPES = ("Real", "Float32", "Float64")
TRUE_STRINGS = ("true", "1", "yes", "on")
FALSE_STRINGS = ("false", "0", "no", "off", "")

# Interval qualifiers (FMI 3)
INTERVAL_NOT_YET_KNOWN, INTERVAL_UNCHANGED, INTERVAL_CHANGED = 0, 1, 2


class Status:
    """FMI status codes; identical numbering in FMI 2 and FMI 3."""
    ok = 0
    warning = 1
    discard = 2
    error = 3
    fatal = 4


class StepRejected(Exception):
    """A step the FMU can't complete ([model] integrate: the solver failed); doStep returns discard."""
