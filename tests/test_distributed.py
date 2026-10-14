"""Distributed FMUs (--distributed): a proxy FMU, and a private folder that runs the model and connects to it."""
import re
import subprocess
import sys
import tomllib
import zipfile

import pytest
from conftest import EXAMPLES
from fmpy import simulate_fmu

from fmugen.__main__ import build
from fmugen.config import InterfaceError

for _module in ("toml", "coloredlogs", "colorama"):   # fmugen[distributed]: the private side imports them
    pytest.importorskip(_module)

PORT = re.compile(rb"dispatcher through port:\s*(\d+)")


def _simulate(fmu, private, command, fmi_version=2, output="output", **options):
    """Simulate the proxy, starting the private side with the port the proxy logs (UniFMU picks it)."""
    started = []

    def connect(message):
        found = PORT.search(message if isinstance(message, bytes) else message.encode())
        if found and not started:
            started.append(subprocess.Popen([*command, found.group(1).decode()], cwd=private,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    logger = ((lambda env, instance, status, category, message: connect(message)) if fmi_version == 2 else
              (lambda env, status, category, message: connect(message)))
    try:
        result = simulate_fmu(str(fmu), output=[output], debug_logging=True, logger=logger,
                              **{"stop_time": 1, **options})
    finally:
        for process in started:
            process.wait(timeout=300)   # a vendored first run installs its wheels
    assert started, "the proxy didn't log its port"
    return list(result[output])


def test_options_need_distributed(tmp_path):
    with pytest.raises(InterfaceError, match="only apply with --distributed"):
        build(EXAMPLES / "simple_pid", tmp_path / "a.fmu", endpoint="10.0.0.5")
    with pytest.raises(InterfaceError, match="only apply with --distributed"):
        build(EXAMPLES / "simple_pid", tmp_path / "a.fmu", private_output=tmp_path / "p")


@pytest.mark.parametrize("fmi_version", [2, 3])
def test_proxy_and_private_side_simulate_like_a_normal_fmu(tmp_path, fmi_version):
    expected = list(simulate_fmu(str(build(EXAMPLES / "simple_pid", tmp_path / "pid.fmu", fmi_version=fmi_version)[0]),
                                 stop_time=1, output=["output"])["output"])

    fmu, interface = build(EXAMPLES / "simple_pid", tmp_path / "proxy.fmu", fmi_version=fmi_version,
                           distributed=True, endpoint="127.0.0.1")
    private = tmp_path / "proxy_private"
    assert interface["private_output"] == private
    with zipfile.ZipFile(fmu) as z:
        names = z.namelist()
        assert tomllib.loads(z.read("resources/launch.toml").decode()) == {"location": "Remote"}
    assert not any(n.endswith(".py") or n.endswith("interface.json") for n in names)
    assert any(n.startswith("binaries/") for n in names)

    assert tomllib.loads((private / "endpoint.toml").read_text()) == {"ip": "127.0.0.1"}
    assert {"toml", "coloredlogs", "colorama"} <= set((private / "requirements.txt").read_text().split())
    assert (private / "interface.json").exists() and (private / "model.py").exists()

    assert _simulate(fmu, private, [sys.executable, "main.py"], fmi_version) == expected


def test_vendored_private_side_installs_its_wheels(tmp_path, monkeypatch):
    monkeypatch.setenv("FMUGEN_ENV_DIR", str(tmp_path / "envs"))
    expected = list(simulate_fmu(str(build(EXAMPLES / "simple_pid", tmp_path / "pid.fmu")[0]),
                                 stop_time=1, output=["output"])["output"])
    fmu, interface = build(EXAMPLES / "simple_pid", tmp_path / "proxy.fmu", vendor=True, distributed=True,
                           private_output=tmp_path / "elsewhere")
    private = tmp_path / "elsewhere"
    wheels = {p.name.split("-")[0].lower() for p in (private / "wheels").glob("*.whl")}
    assert {"toml", "coloredlogs", "colorama", "pyzmq"} <= wheels
    assert interface["private_start"].endswith("fmugen_launch.py PORT")
    assert _simulate(fmu, private, [sys.executable, "fmugen_launch.py"]) == expected


def test_composite_distributed(tmp_path):
    from test_composite import closed_loop, write_composite
    fmu, interface = build(write_composite(tmp_path), tmp_path / "loop.fmu", distributed=True)
    result = _simulate(fmu, interface["private_output"], [sys.executable, "main.py"], output="tank.y",
                       stop_time=5.0, output_interval=1.0, start_values={"valve.setpoint": 3.0})
    assert result[1:] == pytest.approx(closed_loop(5, setpoint=3.0))
