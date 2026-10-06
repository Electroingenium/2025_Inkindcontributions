"""Composite FMUs: several fmugen models in one FMU, connected output to input."""
import textwrap

import pytest
from fmpy import read_model_description, simulate_fmu
from fmpy.validation import validate_fmu

from fmugen.__main__ import build, init
from fmugen.config import InterfaceError

OK = 0

TANK = """
class Tank:
    def __init__(self, area=2.0):
        self.area, self.level = area, 1.0

    def step(self, inflow: float = 0.0, dt=1.0):
        self.level += (inflow - 0.1 * self.level) / self.area * dt
        return self.level
"""

VALVE = """
def valve(level: float = 1.0, setpoint: float = 2.0, gain: float = 0.5):
    return {"flow": max(0.0, gain * (setpoint - level))}
"""


def write_composite(tmp_path, connections=("valve.flow -> tank.inflow", "tank.level -> valve.level")):
    for name, source in (("tank", TANK), ("valve", VALVE)):
        (tmp_path / name).mkdir(exist_ok=True)
        (tmp_path / name / f"{name}.py").write_text(source)
        init(tmp_path / name / f"{name}.py", force=True)
    lines = ", ".join(f'"{c}"' for c in connections)
    (tmp_path / "fmugen.toml").write_text(textwrap.dedent(f"""
        [composite]
        name = "tank_loop"
        parts = {{ valve = "valve", tank = "tank" }}
        connections = [{lines}]
    """))
    return tmp_path / "fmugen.toml"


def closed_loop(steps, setpoint=2.0):
    """The same loop, run directly in Python."""
    namespace = {}
    exec(TANK + VALVE, namespace)
    tank, levels = namespace["Tank"](), []
    for _ in range(steps):
        flow = namespace["valve"](level=tank.level, setpoint=setpoint)["flow"]
        levels.append(tank.step(inflow=flow))
    return levels


@pytest.mark.parametrize("fmi", [2, 3])
def test_composite_closed_loop_matches_the_models(tmp_path, adapter, fmi):
    out = tmp_path / "fmu"
    _, interface = build(write_composite(tmp_path), out, output_format="folder", fmi_version=fmi)
    names = [v["name"] for v in interface["variables"]]
    assert "tank.inflow" not in names and "valve.level" not in names    # fed by connections
    assert {"valve.setpoint", "valve.gain", "tank.area", "tank.y", "valve.flow"} <= set(names)

    fmu = adapter(out, fmi=fmi)
    fmu.initialize()
    step = fmu.fmi3DoStep if fmi == 3 else fmu.fmi2DoStep
    levels = []
    for t in range(5):
        status = step(float(t), 1.0, False)
        assert (status[0] if fmi == 3 else status) == OK, fmu.logs
        levels.append(fmu.get("tank.y"))
    assert levels == closed_loop(5)


def test_composite_state_rollback_and_reset(tmp_path, adapter):
    out = tmp_path / "fmu"
    build(write_composite(tmp_path), out, output_format="folder")
    fmu = adapter(out)
    fmu.initialize()
    for t in range(3):
        assert fmu.fmi2DoStep(float(t), 1.0, False) == OK
    _, state = fmu.fmi2SerializeFmuState()
    assert fmu.fmi2DoStep(3.0, 1.0, False) == OK
    after = fmu.get("tank.y")
    assert fmu.fmi2DeserializeFmuState(state) == OK
    assert fmu.fmi2DoStep(3.0, 1.0, False) == OK and fmu.get("tank.y") == after
    assert fmu.fmi2Reset() == OK
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK and fmu.get("tank.y") == closed_loop(1)[0]


def test_composite_through_unifmu(tmp_path):
    fmu = tmp_path / "loop.fmu"
    build(write_composite(tmp_path), fmu)
    assert validate_fmu(str(fmu)) == []
    assert {v.name for v in read_model_description(str(fmu)).modelVariables} >= {"tank.y", "valve.setpoint"}
    result = simulate_fmu(str(fmu), stop_time=5.0, output_interval=1.0, start_values={"valve.setpoint": 3.0},
                          output=["tank.y"])
    assert list(result["tank.y"][1:]) == pytest.approx(closed_loop(5, setpoint=3.0))


@pytest.mark.parametrize("connections, message", [
    (["valve.flow -> tank.nope"], "has no variable"),
    (["valve.flow -> pump.inflow"], "no part"),
    (["valve.flow -> tank.y"], "not an input"),
    (["valve.flow -> tank.inflow", "valve.flow -> tank.inflow"], "fed twice"),
    (["valve.flow to tank.inflow"], "must look like"),
])
def test_composite_connection_errors(tmp_path, connections, message):
    with pytest.raises(InterfaceError, match=message):
        build(write_composite(tmp_path, connections), tmp_path / "out", output_format="folder")


def test_composite_cannot_be_compiled_yet(tmp_path):
    with pytest.raises(InterfaceError, match="--compile"):
        build(write_composite(tmp_path), tmp_path / "out.fmu", compiler="pyinstaller")
