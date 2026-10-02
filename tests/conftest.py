import contextlib
import sys
from pathlib import Path

import pytest

from fmugen.__main__ import build, isolated_imports
from fmugen.templates import model as runtime

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class Adapter:
    """Drives the generated adapter (resources/model.py) directly, without UniFMU or zmq."""

    def __init__(self, resources):
        self.logs = []
        self.model = runtime.Model(lambda status, category, message: self.logs.append((status, category, message)),
                                   resources_dir=resources)
        self.vr = {v["name"]: v["valueReference"] for v in self.model.variables}

    def __getattr__(self, name):
        return getattr(self.model, name)

    def get(self, *names):
        status, values = self.model.fmi2GetReal([self.vr[n] for n in names])
        assert status == runtime.Fmi2Status.ok
        return values[0] if len(names) == 1 else values

    def set(self, name, value):
        setter = {bool: self.model.fmi2SetBoolean, int: self.model.fmi2SetInteger,
                  str: self.model.fmi2SetString}.get(type(value), self.model.fmi2SetReal)
        return setter([self.vr[name]], [value])

    def initialize(self, start=0.0):
        assert self.model.fmi2SetupExperiment(start, None, None) == runtime.Fmi2Status.ok
        assert self.model.fmi2EnterInitializationMode() == runtime.Fmi2Status.ok
        assert self.model.fmi2ExitInitializationMode() == runtime.Fmi2Status.ok, self.logs


@pytest.fixture
def make_fmu(tmp_path):
    """Build a target into an unzipped FMU folder and return the folder."""
    counter = iter(range(100))

    def make(target, **kwargs):
        out = tmp_path / f"fmu{next(counter)}"
        build(target, out, output_format="folder", python_exec=sys.executable, **kwargs)
        return out
    return make


@pytest.fixture
def adapter():
    """Open the adapter of a built FMU folder; imports are undone afterwards."""
    with contextlib.ExitStack() as stack:
        def open_(fmu_dir):
            stack.enter_context(isolated_imports())
            return Adapter(Path(fmu_dir) / "resources")
        yield open_
