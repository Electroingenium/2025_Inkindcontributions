"""Composite FMUs: several fmugen models in one FMU, connected output to input."""
import importlib.util
import textwrap
import zipfile

import pytest
from fmpy import read_model_description, simulate_fmu
from fmpy.validation import validate_fmu

from fmugen.builder import build, init
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


@pytest.mark.fmu
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


@pytest.mark.slow
@pytest.mark.fmu
def test_compiled_composite_has_no_sources_and_simulates(tmp_path):
    if not importlib.util.find_spec("PyInstaller"):
        pytest.skip("PyInstaller is not installed")
    fmu = build(write_composite(tmp_path), tmp_path / "loop.fmu", compiler="pyinstaller")[0]
    with zipfile.ZipFile(fmu) as z:
        names = z.namelist()
    assert not any(n.endswith(".py") for n in names)
    assert [n for n in names if n.startswith("resources/") and not n.startswith("resources/dist/")
            and not n.endswith("/")] == ["resources/launch.toml"]
    result = simulate_fmu(str(fmu), stop_time=5.0, output_interval=1.0, start_values={"valve.setpoint": 3.0},
                          output=["tank.y"])
    assert list(result["tank.y"][1:]) == pytest.approx(closed_loop(5, setpoint=3.0))


def test_composite_parts_with_modules_of_the_same_name_are_refused(tmp_path):
    # both parts import their own utils.py: in one process, the second would get the first's
    for name, value in (("a", 1.0), ("b", 2.0)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "utils.py").write_text(f"GAIN = {value}\n")
        (tmp_path / name / f"{name}.py").write_text(f"from utils import GAIN\n\ndef {name}(x: float = 1.0):\n"
                                                    f"    return {{'y': GAIN * x}}\n")
        init(tmp_path / name / f"{name}.py", force=True)
    (tmp_path / "fmugen.toml").write_text('[composite]\nparts = { a = "a", b = "b" }\nconnections = ["a.y -> b.x"]\n')
    with pytest.raises(InterfaceError, match=r"utils \(in a, b\)"):
        build(tmp_path / "fmugen.toml", tmp_path / "out", output_format="folder")


@pytest.mark.parametrize("fmi", [2, 3])
def test_composite_connection_types_are_checked(tmp_path, fmi):
    path = write_composite(tmp_path, ["valve.state -> tank.inflow"])
    (tmp_path / "valve" / "valve.py").write_text(VALVE.replace('return {"flow"', 'return {"state": "open", "flow"'))
    init(tmp_path / "valve" / "valve.py", force=True)
    with pytest.raises(InterfaceError, match="valve.state -> tank.inflow: a String can't be passed to a"):
        build(path, tmp_path / "out", output_format="folder", fmi_version=fmi)


def test_composite_of_parts_with_clocks_and_structural_parameters(tmp_path, adapter):
    from conftest import EXAMPLES
    (tmp_path / "fmugen.toml").write_text(textwrap.dedent(f"""
        [composite]
        fmi_version = 3
        parts = {{ pid = "{(EXAMPLES / 'sampled_pid').as_posix()}", kf = "{(EXAMPLES / 'kalman').as_posix()}" }}
    """))
    out = tmp_path / "fmu"
    _, interface = build(tmp_path / "fmugen.toml", out, output_format="folder")
    assert [c["name"] for c in interface["clocks"]] == ["pid.sample", "kf.measurement"]
    assert interface["has_event_mode"] and interface["experiment"]["step_size"] == 0.1
    by_name = {v["name"]: v for v in interface["variables"]}
    assert by_name["kf.x"]["dimensions"] == ["kf.dim_x"] and by_name["kf.z"]["clocks"] == ["kf.measurement"]

    fmu = adapter(out, fmi=3, event_mode_used=True)
    assert fmu.fmi3EnterConfigurationMode() == OK              # only the Kalman filter has structural parameters
    assert fmu.set("kf.dim_z", 1) == OK
    assert fmu.fmi3ExitConfigurationMode() == OK
    fmu.initialize()                                           # -> event mode
    assert fmu.fmi3GetIntervalDecimal([fmu.vr["pid.sample"], fmu.vr["kf.measurement"]]) == (OK, [0.1, 0.0], [2, 0])
    assert fmu.fmi3SetClock([fmu.vr["pid.sample"]], [True]) == OK
    assert fmu.fmi3UpdateDiscreteStates()[0] == OK, fmu.logs
    assert fmu.get("pid.output") == pytest.approx(2.0 + 0.5 * 0.1)
    assert fmu.fmi3GetClock([fmu.vr["pid.sample"], fmu.vr["kf.measurement"]]) == (OK, [True, False])
    assert fmu.fmi3EnterStepMode() == OK
    t = 0.0
    for k in range(9):                                          # an object moving at 1 m/s
        assert fmu.fmi3DoStep(t, 0.1, False)[0] == OK, fmu.logs
        t += 0.1
        if k % 3 == 2:
            assert fmu.fmi3EnterEventMode() == OK
            assert fmu.set("kf.z", [t]) == OK
            assert fmu.fmi3SetClock([fmu.vr["kf.measurement"]], [True]) == OK
            assert fmu.fmi3UpdateDiscreteStates()[0] == OK, fmu.logs
            assert fmu.fmi3EnterStepMode() == OK
    assert fmu.engine.get_values([fmu.vr["kf.x"]])[1][0] == pytest.approx(t, abs=0.2)
    assert fmu.get("pid.output") == pytest.approx(2.05)        # the PID only runs when its clock ticks


def test_clocked_variables_cannot_be_connected(tmp_path):
    from conftest import EXAMPLES
    (tmp_path / "fmugen.toml").write_text(textwrap.dedent(f"""
        [composite]
        fmi_version = 3
        parts = {{ pid = "{(EXAMPLES / 'sampled_pid').as_posix()}", kf = "{(EXAMPLES / 'kalman').as_posix()}" }}
        connections = ["pid.output -> kf.z"]
    """))
    with pytest.raises(InterfaceError, match="clocked variable"):
        build(tmp_path / "fmugen.toml", tmp_path / "out", output_format="folder")
