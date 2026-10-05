"""FMI 3: the generated adapter driven directly, and built FMUs driven through UniFMU."""
import shutil
import sys
import textwrap
from ctypes import c_double, c_int, c_uint64

import pytest
from fmpy import read_model_description
from fmpy.fmi3 import FMU3Slave, fmi3ValueReference
from fmpy.validation import validate_fmu

from conftest import EXAMPLES
from fmugen.__main__ import build
from fmugen.config import InterfaceError
from fmugen.templates.fmugen_runtime import Status

OK, WARNING, ERROR = Status.ok, Status.warning, Status.error


def write(tmp_path, source, config):
    (tmp_path / "m.py").write_text(textwrap.dedent(source))
    (tmp_path / "fmugen.toml").write_text(textwrap.dedent(config))
    return tmp_path


# ---------------- the adapter, directly ----------------

def test_arrays_binary_and_integer_types(tmp_path, make_fmu, adapter):
    write(tmp_path, '''
        def f(v=(1.0, 2.0, 3.0), m=((1, 2), (3, 4)), key=b"\\x0f", n=1):
            return {"total": sum(v), "row_sums": [sum(r) for r in m], "masked": bytes(b ^ 0xff for b in key),
                    "double": 2 * n}
    ''', '''
        [model]
        entry = "m.py:f"
        fmi_version = 3
        [inputs]
        v   = { dimensions = [3], start = [1.0, 2.0, 3.0] }
        m   = { dimensions = [2, 2], type = "Int16", start = 7 }      # scalar start broadcast
        key = { type = "Binary", start = "0f" }
        n   = { type = "UInt8", start = 1 }
        [outputs]
        total    = {}
        row_sums = { dimensions = [2], type = "Int32" }
        masked   = { type = "Binary" }
        double   = { type = "UInt16" }
    ''')
    fmu = adapter(make_fmu(tmp_path), fmi=3)
    fmu.initialize()
    assert fmu.get("m") == 7                                   # first of the flattened values
    assert fmu.engine.get_values([fmu.vr["m"]]) == (OK, [7, 7, 7, 7])
    assert fmu.get("total", "row_sums", "masked", "double") == [6.0, 14, 14, b"\xf0", 2]

    assert fmu.fmi3SetFloat64([fmu.vr["v"]], [1.0, 1.0, 1.0]) == OK
    assert fmu.fmi3SetInt16([fmu.vr["m"]], [1, 2, 3, 4]) == OK
    assert fmu.fmi3SetBinary([fmu.vr["key"]], [2], [b"\x00\x01"]) == OK
    assert fmu.fmi3SetUInt8([fmu.vr["n"]], [256]) == ERROR      # out of range for UInt8
    assert fmu.fmi3DoStep(0.0, 1.0, False)[0] == OK
    assert fmu.engine.get_values([fmu.vr["row_sums"], fmu.vr["total"]]) == (OK, [3, 7, 3.0])
    assert fmu.fmi3GetBinary([fmu.vr["masked"]]) == (OK, [b"\xff\xfe"])


def test_structural_parameter_resizes_arrays(tmp_path, make_fmu, adapter):
    write(tmp_path, '''
        import numpy as np

        class Smoother:
            def __init__(self, n=3):
                self.window = np.zeros(n)

            def step(self, u):
                self.window = np.roll(self.window, 1)
                self.window[0] = u
                return float(self.window.mean())
    ''', '''
        [model]
        entry = "m.py:Smoother"
        call = "step"
        fmi_version = 3
        [structural_parameters]
        n = { start = 3 }
        [inputs]
        u = { start = 1.0 }
        [outputs]
        mean = { from = "return" }
        window = { dimensions = ["n"] }
    ''')
    fmu = adapter(make_fmu(tmp_path), fmi=3)
    assert fmu.set("n", 4) == ERROR                            # only in configuration mode
    assert fmu.fmi3EnterConfigurationMode() == OK
    assert fmu.fmi3SetUInt64([fmu.vr["n"]], [4]) == OK
    assert fmu.fmi3ExitConfigurationMode() == OK
    assert fmu.engine.get_values([fmu.vr["window"]]) == (OK, [0.0] * 4)
    fmu.initialize()
    assert fmu.fmi3DoStep(0.0, 1.0, False)[0] == OK
    assert fmu.get("mean") == 0.25
    assert fmu.engine.get_values([fmu.vr["window"]]) == (OK, [1.0, 0.0, 0.0, 0.0])


def test_periodic_clock_runs_code_only_when_ticked(make_fmu, adapter):
    fmu = adapter(make_fmu(EXAMPLES / "sampled_pid"), fmi=3, event_mode_used=True)
    fmu.initialize()                                           # -> event mode
    assert fmu.fmi3GetIntervalDecimal([fmu.vr["sample"]]) == (OK, [0.1], [2])
    assert fmu.fmi3GetIntervalDecimal([fmu.vr["sample"]]) == (OK, [0.1], [1])   # unchanged since
    assert fmu.fmi3GetIntervalFraction([fmu.vr["sample"]]) == (OK, [1], [10], [1])

    assert fmu.fmi3SetClock([fmu.vr["sample"]], [True]) == OK
    assert fmu.fmi3UpdateDiscreteStates()[0] == OK
    assert fmu.get("output") == pytest.approx(2.0 + 0.5 * 0.1)   # dt = interval on the first tick
    assert fmu.fmi3EnterStepMode() == OK
    assert fmu.fmi3GetClock([fmu.vr["sample"]]) == (OK, [False])   # deactivated in step mode

    for t in (0.0, 0.05):                                     # no tick: the PID doesn't run
        assert fmu.fmi3DoStep(t, 0.05, False)[0] == OK
    assert fmu.get("output") == pytest.approx(2.05)
    assert fmu.fmi3EnterEventMode() == OK
    assert fmu.fmi3SetClock([fmu.vr["sample"]], [True]) == OK
    assert fmu.fmi3UpdateDiscreteStates()[0] == OK
    assert fmu.get("output") == pytest.approx(2.0 + 0.5 * 0.2)   # dt = time since the last tick

    status, saved = fmu.fmi3SerializeFmuState()
    assert status == OK
    assert fmu.fmi3EnterStepMode() == OK
    assert fmu.fmi3DoStep(0.1, 0.1, False)[0] == OK
    assert fmu.fmi3DeserializeFmuState(saved) == OK            # rollback restores the clock state too
    assert fmu.engine.clock_active["sample"] is True and fmu.engine.mode == "event"


def test_triggered_clock_with_array_input(make_fmu, adapter):
    fmu = adapter(make_fmu(EXAMPLES / "kalman"), fmi=3, event_mode_used=True)
    fmu.initialize()
    assert fmu.fmi3GetIntervalDecimal([fmu.vr["measurement"]]) == (OK, [0.0], [0])   # triggered: not known
    assert fmu.fmi3EnterStepMode() == OK
    t = 0.0
    for k in range(30):                                        # object moving at 1 m/s
        assert fmu.fmi3DoStep(t, 0.1, False)[0] == OK
        t += 0.1
        if k % 3 == 2:                                         # a measurement every 0.3 s
            assert fmu.fmi3EnterEventMode() == OK
            assert fmu.set("z", [t]) == OK
            assert fmu.fmi3SetClock([fmu.vr["measurement"]], [True]) == OK
            assert fmu.fmi3UpdateDiscreteStates()[0] == OK, fmu.logs
            assert fmu.fmi3EnterStepMode() == OK
    position, velocity = fmu.engine.get_values([fmu.vr["x"]])[1]
    assert position == pytest.approx(t, abs=0.1)
    assert velocity == pytest.approx(1.0, abs=0.15)
    assert fmu.fmi3DoStep(t, 0.2, False)[0] == ERROR           # fixed step size


def test_output_clock_and_terminate(tmp_path, make_fmu, adapter):
    write(tmp_path, '''
        class Tank:
            def __init__(self, capacity=3.0):
                self.capacity, self.level, self.overflowed = capacity, 0.0, False

            def fill(self, inflow, dt):
                self.level += inflow * dt
                self.overflowed = self.level > self.capacity
                self.full = self.level >= 2 * self.capacity
    ''', '''
        [model]
        entry = "m.py:Tank"
        call = "fill"
        fmi_version = 3
        [time]
        dt = "step_size"
        [parameters]
        capacity = { start = 3.0 }
        [inputs]
        inflow = { start = 1.0 }
        [clocks.overflow]
        causality = "output"
        from = "attr:overflowed"
        [outputs]
        level = {}
        spill = { from = "attr:level", clocks = ["overflow"] }
        [events]
        terminate = "attr:full"
    ''')
    fmu = adapter(make_fmu(tmp_path), fmi=3, event_mode_used=True)
    fmu.initialize()
    assert fmu.fmi3EnterStepMode() == OK
    results = [fmu.fmi3DoStep(t, 1.0, False) for t in (0.0, 1.0, 2.0)]
    assert [r[1] for r in results] == [False, False, False]
    status, event_needed, terminate, early_return, last_time = fmu.fmi3DoStep(3.0, 1.0, False)
    assert (status, event_needed, terminate, early_return, last_time) == (OK, True, False, False, 4.0)
    assert fmu.fmi3EnterEventMode() == OK
    assert fmu.fmi3GetClock([fmu.vr["overflow"]]) == (OK, [True])
    assert fmu.fmi3GetClock([fmu.vr["overflow"]]) == (OK, [False])   # reset once read
    assert fmu.get("spill") == 4.0
    assert fmu.fmi3EnterStepMode() == OK
    assert fmu.fmi3DoStep(4.0, 2.0, False)[2] is True                 # level 6 = 2 * capacity


def test_fmi3_only_features_are_rejected_for_fmi2(tmp_path):
    write(tmp_path, "def f(v=(1.0, 2.0)):\n    return {'s': sum(v)}\n", '''
        [model]
        entry = "m.py:f"
        [inputs]
        v = { dimensions = [2], start = [1.0, 2.0] }
        [outputs]
        s = {}
    ''')
    with pytest.raises(InterfaceError, match="requires FMI 3"):
        build(tmp_path, tmp_path / "out.fmu")
    build(tmp_path, tmp_path / "out3.fmu", fmi_version=3)
    assert validate_fmu(str(tmp_path / "out3.fmu")) == []


# ---------------- through UniFMU ----------------

@pytest.fixture(scope="module")
def fmus(tmp_path_factory):
    out = tmp_path_factory.mktemp("fmus3")
    return {name: build(EXAMPLES / name, out / f"{name}.fmu", fmi_version=3)[0]
            for name in ("sampled_pid", "kalman", "simple_pid")}


@pytest.fixture
def slave(fmus, tmp_path):
    instances = []

    def open_(name, event_mode_used=True):
        unzipdir = tmp_path / name
        shutil.unpack_archive(fmus[name], unzipdir, "zip")
        md = read_model_description(str(unzipdir))
        fmu = FMU3Slave(guid=md.guid, unzipDirectory=str(unzipdir), modelIdentifier="unifmu", instanceName=name)
        fmu.instantiate(eventModeUsed=event_mode_used)
        instances.append(fmu)
        return fmu, {v.name: v.valueReference for v in md.modelVariables}
    yield open_
    for fmu in instances:
        fmu.freeInstance()


def test_clocks_intervals_and_state_through_unifmu(slave):
    fmu, vr = slave("sampled_pid")
    clock = (fmi3ValueReference * 1)(vr["sample"])
    fmu.enterInitializationMode(startTime=0.0)
    fmu.setFloat64([vr["Kp"]], [4.0])
    fmu.exitInitializationMode()                               # -> event mode

    intervals, qualifiers = (c_double * 1)(), (c_int * 1)()
    fmu.getIntervalDecimal(clock, intervals, qualifiers)
    assert (intervals[0], qualifiers[0]) == (0.1, 2)
    counters, resolutions = (c_uint64 * 1)(), (c_uint64 * 1)()
    fmu.getIntervalFraction(clock, counters, resolutions, qualifiers)
    assert (counters[0], resolutions[0]) == (1, 10)
    shifts = (c_double * 1)()
    fmu.getShiftDecimal(clock, shifts)
    assert shifts[0] == 0.0
    fmu.getShiftFraction(clock, counters, resolutions)
    assert (counters[0], resolutions[0]) == (0, 1)

    fmu.setClock([vr["sample"]], [True])
    fmu.setFloat64([vr["measurement"]], [0.5])
    fmu.updateDiscreteStates()
    assert fmu.getFloat64([vr["output"]])[0] == pytest.approx(4.0 * 0.5 + 0.5 * 0.5 * 0.1)
    fmu.enterStepMode()
    state = fmu.getFMUState()
    fmu.doStep(0.0, 0.05)
    fmu.setFMUState(state)
    fmu.doStep(0.0, 0.05)
    assert len(fmu.serializeFMUState(state)) > 0
    fmu.terminate()


def test_kalman_and_configuration_mode_through_unifmu(slave):
    fmu, vr = slave("kalman")
    fmu.enterConfigurationMode()
    fmu.setUInt64([vr["dim_x"]], [2])
    fmu.exitConfigurationMode()
    fmu.enterInitializationMode(startTime=0.0)
    fmu.exitInitializationMode()
    fmu.enterStepMode()
    for k in range(10):
        fmu.doStep(k * 0.1, 0.1)
    fmu.enterEventMode()
    fmu.setFloat64([vr["z"]], [1.0])
    fmu.setClock([vr["measurement"]], [True])
    fmu.updateDiscreteStates()
    fmu.enterStepMode()
    x = fmu.getFloat64([vr["x"]], nValues=2)
    assert 0.0 < x[0] <= 1.0
    assert len(fmu.getFloat64([vr["P"]], nValues=4)) == 4
    fmu.terminate()
    fmu.reset()


ALL_TYPES = {
    "Float32": 1.5, "Float64": 2.25, "Int8": -8, "UInt8": 200, "Int16": -1600, "UInt16": 60000,
    "Int32": -2**31, "UInt32": 2**32 - 1, "Int64": -2**62, "UInt64": 2**64 - 1,
    "Boolean": True, "String": "héllo", "Binary": b"\x00\xff",
}


def test_every_type_clock_setting_and_state_function_through_unifmu(tmp_path):
    names = {t: t.lower() for t in ALL_TYPES}
    args = ", ".join(f"{n}_in" for n in names.values())
    returns = ", ".join(f'"{n}_out": {n}_in' for n in names.values())
    inputs = "\n".join(f'{n}_in = {{ type = "{t}" }}' for t, n in names.items())
    outputs = "\n".join(f'{n}_out = {{ type = "{t}" }}' for t, n in names.items())
    write(tmp_path, f"def echo({args}):\n    return {{{returns}}}\n", f'''
[model]
entry = "m.py:echo"
fmi_version = 3
[clocks.fixed_clock]
interval_variability = "fixed"
interval = 1.0
[clocks.tunable_clock]
interval_variability = "tunable"
interval = 2.0
[inputs]
{inputs}
[outputs]
{outputs}
''')
    out = build(tmp_path, tmp_path / "echo.fmu")[0]
    assert validate_fmu(str(out)) == []
    unzipdir = tmp_path / "echo"
    shutil.unpack_archive(out, unzipdir, "zip")
    md = read_model_description(str(unzipdir))
    vr = {v.name: v.valueReference for v in md.modelVariables}
    fmu = FMU3Slave(guid=md.guid, unzipDirectory=str(unzipdir), modelIdentifier="unifmu", instanceName="echo")
    assert fmu.getVersion() == "3.0"
    fmu.instantiate(eventModeUsed=True)
    try:
        fixed = (fmi3ValueReference * 1)(vr["fixed_clock"])
        tunable = (fmi3ValueReference * 1)(vr["tunable_clock"])
        fmu.enterInitializationMode(startTime=0.0)
        fmu.setIntervalDecimal(fixed, (c_double * 1)(0.5))
        fmu.fmi3SetShiftDecimal(fmu.component, fixed, 1, (c_double * 1)(0.25))
        fmu.setIntervalFraction(tunable, (c_uint64 * 1)(3), (c_uint64 * 1)(4))
        for t, value in ALL_TYPES.items():
            getattr(fmu, f"set{t}")([vr[f"{names[t]}_in"]], [value])
        fmu.exitInitializationMode()

        intervals, qualifiers, shifts = (c_double * 2)(), (c_int * 2)(), (c_double * 2)()
        both = (fmi3ValueReference * 2)(vr["fixed_clock"], vr["tunable_clock"])
        fmu.getIntervalDecimal(both, intervals, qualifiers)
        fmu.getShiftDecimal(both, shifts)
        assert list(intervals) == [0.5, 0.75] and list(shifts) == [0.25, 0.0]
        fmu.setIntervalDecimal(tunable, (c_double * 1)(1.25))      # tunable: allowed in event mode
        fmu.getIntervalDecimal(tunable, intervals, qualifiers)
        assert (intervals[0], qualifiers[0]) == (1.25, 2)
        with pytest.raises(Exception):
            fmu.setIntervalDecimal(fixed, (c_double * 1)(2.0))     # fixed: only before initialization ends

        fmu.enterStepMode()
        fmu.doStep(0.0, 0.5)
        for t, value in ALL_TYPES.items():
            assert getattr(fmu, f"get{t}")([vr[f"{names[t]}_out"]]) == [value], t

        state = fmu.getFMUState()
        serialized = fmu.serializeFMUState(state)
        fmu.setFloat64([vr["float64_in"]], [9.0])
        fmu.doStep(0.5, 0.5)
        assert fmu.getFloat64([vr["float64_out"]]) == [9.0]
        restored = fmu.deserializeFMUState(serialized)
        fmu.setFMUState(restored)
        assert fmu.getFloat64([vr["float64_out"]]) == [2.25]
        fmu.freeFMUState(state)
        fmu.freeFMUState(restored)
        fmu.terminate()
    finally:
        fmu.freeInstance()


@pytest.mark.parametrize("name", ["psychrometry", "simple_pid", "rc_building"])
def test_fmi2_examples_build_as_fmi3_with_the_same_results(tmp_path, name):
    from fmpy import simulate_fmu
    kwargs = dict(stop_time=7200 if name == "rc_building" else 1.0, output_interval=3600 if name == "rc_building" else 0.1)
    results = {}
    for version in (2, 3):
        out = build(EXAMPLES / name, tmp_path / f"{name}{version}.fmu", fmi_version=version)[0]
        assert validate_fmu(str(out)) == []
        results[version] = simulate_fmu(str(out), **kwargs)
    assert results[2].dtype.names == results[3].dtype.names
    for column in results[2].dtype.names:
        assert list(results[2][column]) == pytest.approx(list(results[3][column]), nan_ok=True)


def test_plain_cosimulation_without_event_mode(fmus):
    from fmpy import simulate_fmu
    result = simulate_fmu(str(fmus["simple_pid"]), stop_time=1.0, output=["output"])
    assert result["output"][-1] == pytest.approx(2.0 + 0.5 * 1.0)
