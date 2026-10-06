"""FMUs for other machines: vendored wheels (--vendor) and frozen executables (--compile)."""
import importlib.util
import tomllib
import zipfile

import pytest
from fmpy import simulate_fmu

from conftest import EXAMPLES
from fmugen.__main__ import build
from fmugen.config import InterfaceError


def _contents(fmu):
    with zipfile.ZipFile(fmu) as z:
        return tomllib.loads(z.read("resources/launch.toml").decode()), z.namelist()


def _simulate_pid(fmu):
    return simulate_fmu(str(fmu), stop_time=1, output=["output"])["output"]


def test_options_are_checked(tmp_path):
    with pytest.raises(InterfaceError, match="exclude each other"):
        build(EXAMPLES / "simple_pid", tmp_path / "a.fmu", vendor=True, compiler="pyinstaller")
    with pytest.raises(InterfaceError, match="only apply with --vendor"):
        build(EXAMPLES / "simple_pid", tmp_path / "b.fmu", platforms=["win_amd64"])


def test_vendored_fmu_installs_its_wheels_offline_once(tmp_path, monkeypatch):
    envs = tmp_path / "envs"
    monkeypatch.setenv("FMUGEN_ENV_DIR", str(envs))
    fmu = build(EXAMPLES / "simple_pid", tmp_path / "pid.fmu", vendor=True)[0]
    launch, names = _contents(fmu)
    assert launch["windows"] == ["python", "fmugen_launch.py"] and launch["linux"] == ["python3", "fmugen_launch.py"]
    wheels = {n.split("/")[-1].split("-")[0].lower() for n in names if n.endswith(".whl")}
    assert {"protobuf", "pyzmq", "simple_pid"} <= wheels

    first = _simulate_pid(fmu)
    created = sorted(p.name for p in envs.iterdir())
    assert len(created) == 1 and (envs / created[0] / ".complete").exists()
    second = _simulate_pid(fmu)
    assert sorted(p.name for p in envs.iterdir()) == created
    assert first[-1] != 0 and list(first) == list(second)


@pytest.mark.slow
@pytest.mark.parametrize("compiler", ["pyinstaller", "nuitka"])
def test_compiled_fmu_has_no_sources_and_simulates(tmp_path, compiler):
    module = {"pyinstaller": "PyInstaller", "nuitka": "nuitka"}[compiler]
    if not importlib.util.find_spec(module):
        pytest.skip(f"{module} is not installed")
    fmu = build(EXAMPLES / "simple_pid", tmp_path / "pid.fmu", compiler=compiler)[0]
    launch, names = _contents(fmu)
    assert launch["windows"][0] == "powershell" and "dist/main/main" in launch["linux"][-1]
    resources = [n for n in names if n.startswith("resources/") and not n.startswith("resources/dist/")
                 and not n.endswith("/")]
    assert resources == ["resources/launch.toml"]
    assert not any(n.endswith(".py") for n in names)
    assert _simulate_pid(fmu)[-1] != 0


def test_hugging_face_model_ids_are_found(tmp_path):
    from fmugen.distribute import hf_models
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.csv").write_text("1")
    interface = {
        "variables": [{"start": "amazon/chronos-bolt-tiny"}, {"start": "data/x.csv"}, {"start": "male"},
                      {"start": 1.0}],
        "constants": {"repo": {"python": "'sb3/ppo-CartPole-v1'"}, "n": {"python": "3"}},
    }
    assert hf_models(interface, tmp_path) == ["amazon/chronos-bolt-tiny", "sb3/ppo-CartPole-v1"]
