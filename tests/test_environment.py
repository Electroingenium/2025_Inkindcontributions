"""The FMU runs with the Python fmugen is installed in (the model's virtual environment)."""
import sys
import tomllib
import zipfile

from conftest import EXAMPLES
from fmugen.__main__ import CURRENT_OS, build


def test_fmu_runs_with_this_interpreter_and_lists_its_requirements(tmp_path):
    fmu = build(EXAMPLES / "simple_pid", tmp_path / "pid.fmu")[0]
    with zipfile.ZipFile(fmu) as z:
        launch = tomllib.loads(z.read("resources/launch.toml").decode())
        requirements = [line for line in z.read("resources/requirements.txt").decode().splitlines()
                        if not line.startswith("#")]
    assert launch[CURRENT_OS] == [sys.executable, "main.py"]
    assert requirements == ["protobuf==5.27.3", "pyzmq", "cloudpickle", "simple-pid==2.0.1"]
