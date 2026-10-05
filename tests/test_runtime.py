"""The generated adapter, driven through its FMI 2 methods without UniFMU."""
import importlib.util
import textwrap

import pytest

from conftest import EXAMPLES
from fmugen.templates.model_fmi2 import Fmi2Status

OK, ERROR = Fmi2Status.ok, Fmi2Status.error


def write(tmp_path, name, source, config=None):
    (tmp_path / name).write_text(textwrap.dedent(source))
    if config is not None:
        (tmp_path / "fmugen.toml").write_text(textwrap.dedent(config))
    return tmp_path


def test_function_outputs_match_the_model(make_fmu, adapter):
    fmu = adapter(make_fmu(EXAMPLES / "psychrometry"))
    fmu.initialize()
    spec = importlib.util.spec_from_file_location("psy", EXAMPLES / "psychrometry" / "psychrometry.py")
    psy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(psy)
    inputs = {v["name"]: v["start"] for v in fmu.engine.variables if v["causality"] == "input"}
    expected = psy.compute_balances_simplified(**inputs)
    assert fmu.get("Q_in", "mass_balance") == [expected["Q_in"], expected["mass_balance"]]

    assert fmu.set("temp_1", 30.0) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("Q_in") == pytest.approx(2.4 * 1010 * 30.0)


def test_class_time_argument_and_tunable_parameter(make_fmu, adapter):
    fmu = adapter(make_fmu(EXAMPLES / "simple_pid"))
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 0.1, False) == OK
    assert fmu.get("output") == pytest.approx(2.0 * 1.0 + 0.5 * 1.0 * 0.1)   # Kp*e + Ki*e*dt
    assert fmu.get("integral") == pytest.approx(0.05)

    assert fmu.set("Kp", 4.0) == OK                     # tunable: written onto the PID object
    assert fmu.engine.obj.Kp == 4.0
    assert fmu.fmi2DoStep(0.1, 0.1, False) == OK
    assert fmu.get("output") == pytest.approx(4.0 + 0.1)

    assert fmu.set("proportional_on_measurement", True) == ERROR   # fixed after initialization
    assert fmu.set("output", 1.0) == ERROR                         # outputs cannot be set


def test_state_feedback_fixed_step_and_rollback(make_fmu, adapter):
    fmu = adapter(make_fmu(EXAMPLES / "rc_building"))
    fmu.initialize()
    assert fmu.get("t_air") == 20.0                      # start value until the first step
    assert fmu.get("c_m") == 165000.0 * 35.0            # calculated parameter, read after construction

    assert fmu.fmi2DoStep(0.0, 60.0, False) == ERROR    # only 3600 s steps
    assert "3600" in fmu.logs[-1][2]

    assert fmu.set("t_out", -5.0) == OK
    assert fmu.fmi2DoStep(0.0, 3600.0, False) == OK
    assert fmu.get("t_m_prev") == fmu.engine.obj.t_m_next   # fed back for the next step

    status, saved = fmu.fmi2SerializeFmuState()
    assert status == OK
    assert fmu.fmi2DoStep(3600.0, 3600.0, False) == OK
    first = fmu.get("t_air", "heating_demand", "t_m_prev")
    assert fmu.fmi2DeserializeFmuState(saved) == OK
    assert fmu.fmi2DoStep(3600.0, 3600.0, False) == OK
    assert fmu.get("t_air", "heating_demand", "t_m_prev") == first

    assert fmu.fmi2Reset() == OK
    assert fmu.get("t_m_prev") == 20.0 and fmu.engine.obj is None


def test_parameters_reach_the_constructor(make_fmu, adapter):
    fmu = adapter(make_fmu(EXAMPLES / "rc_building"))
    assert fmu.set("floor_area", 100.0) == OK            # before initialization
    fmu.initialize()
    assert fmu.engine.obj.floor_area == 100.0
    assert fmu.get("c_m") == 165000.0 * 100.0
    assert fmu.set("floor_area", 50.0) == ERROR          # fixed after initialization
    assert fmu.set("t_set_heating", 22.0) == OK          # tunable
    assert fmu.engine.obj.t_set_heating == 22.0


def test_function_with_state_time_and_logging(tmp_path, make_fmu, adapter):
    write(tmp_path, "integrator.py", '''
        import logging
        log = logging.getLogger("integrator")

        def integrate(u, x_prev=0.0, dt=1.0, t=0.0):
            if u > 10:
                log.warning("large input %s at t=%s", u, t)
            return {"x_next": x_prev + u * dt, "time_seen": t}
    ''', '''
        [model]
        entry = "integrator.py:integrate"
        [time]
        dt = "step_size"
        t = "time"
        [inputs]
        u = { start = 1.0 }
        [states]
        x_prev = { start = 0.0, next = "return:x_next" }
        [outputs]
        x = { from = "return:x_next" }
        time_seen = {}
    ''')
    fmu = adapter(make_fmu(tmp_path))
    fmu.initialize()
    assert fmu.get("x_prev") == 0.0                      # initialization does not advance the state
    for t in (0.0, 0.5, 1.0):
        assert fmu.fmi2DoStep(t, 0.5, False) == OK
    assert fmu.get("x", "time_seen") == [1.5, 1.0]

    assert fmu.set("u", 20.0) == OK
    assert fmu.fmi2DoStep(1.5, 0.5, False) == OK
    status, category, message = fmu.logs[-1]
    assert (status, category) == (Fmi2Status.warning, "logStatusWarning")
    assert "large input 20.0 at t=1.5" in message


def test_exceptions_become_errors_with_traceback(tmp_path, make_fmu, adapter):
    write(tmp_path, "fragile.py", '''
        def fragile(x=1.0):
            return {"y": 1.0 / x}
    ''')
    fmu = adapter(make_fmu(tmp_path / "fragile.py"))
    fmu.initialize()
    assert fmu.set("x", 0.0) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == ERROR
    assert "ZeroDivisionError" in fmu.logs[-1][2] and "fragile.py" in fmu.logs[-1][2]


def test_enumeration(tmp_path, make_fmu, adapter):
    write(tmp_path, "valve.py", '''
        import enum

        class Mode(enum.Enum):
            CLOSED = "closed"
            OPEN = "open"

        def valve(flow=1.0, mode=Mode.OPEN):
            return {"out": flow if mode is Mode.OPEN else 0.0, "mode_echo": mode}
    ''')
    fmu = adapter(make_fmu(tmp_path / "valve.py:valve"))
    td = fmu.engine.interface["type_definitions"]["Mode"]
    assert td["items"] == ["CLOSED", "OPEN"]
    fmu.initialize()
    assert fmu.get("out") == 1.0
    assert fmu.fmi2SetInteger([fmu.vr["mode"]], [1]) == OK      # CLOSED
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("out") == 0.0
    assert fmu.fmi2GetInteger([fmu.vr["mode_echo"]]) == (OK, [1])


def test_unpicklable_model_disables_state(tmp_path, make_fmu, adapter):
    write(tmp_path, "gen.py", '''
        class Counter:
            def __init__(self):
                self.it = (i for i in range(1000))   # generators cannot be pickled
                self.count = -1

            def step(self):
                self.count = next(self.it)
    ''')
    fmu_dir = make_fmu(tmp_path / "gen.py")
    xml = (fmu_dir / "modelDescription.xml").read_text()
    assert 'canGetAndSetFMUstate="false"' in xml
    fmu = adapter(fmu_dir)
    fmu.initialize()
    assert fmu.fmi2SerializeFmuState()[0] == ERROR


def test_setup_positional_arguments_and_kind_function(tmp_path, make_fmu, adapter):
    write(tmp_path, "lib.py", '''
        UNITS = None
        SI = "SI"

        def set_units(units):
            global UNITS
            UNITS = units

        def prop(name, value, /, scale=1.0):          # positional-only, like many C extensions
            if UNITS is None:
                raise ValueError("units not set")
            return {"T": value * scale, "P": 2 * value}[name]

        class State:                                   # all the work happens in the constructor
            def __init__(self, **kwargs):
                self.T, self.P = kwargs["T"], kwargs["P"]
                self.rho = self.P / self.T
    ''')
    (tmp_path / "fmugen.toml").write_text(textwrap.dedent('''
        [model]
        entry = "lib.py:prop"
        setup = ["lib:set_units(lib.SI)"]
        [inputs]
        name  = { start = "T", to = "pos:0" }
        value = { start = 3.0, to = "pos:1" }
        scale = { start = 2.0 }
        [outputs]
        y = { from = "return" }
    '''))
    fmu = adapter(make_fmu(tmp_path))
    fmu.initialize()
    assert fmu.get("y") == 6.0
    assert fmu.fmi2SetString([fmu.vr["name"]], ["P"]) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("y") == 6.0 and fmu.engine.module.UNITS == "SI"

    (tmp_path / "fmugen.toml").write_text(textwrap.dedent('''
        [model]
        entry = "lib.py:State"
        kind = "function"
        [inputs]
        T = { start = 300.0 }
        P = { start = 600.0 }
        [outputs]
        rho = { from = "return:rho" }
    '''))
    fmu = adapter(make_fmu(tmp_path))
    fmu.initialize()
    assert fmu.get("rho") == 2.0


def test_setter_method_inputs_and_property_outputs(tmp_path, make_fmu, adapter):
    write(tmp_path, "lab.py", '''
        class Lab:                                     # a hardware-style API
            def __init__(self):
                self._power, self._temp = 0.0, 20.0

            def heater(self, value):                   # set through a method
                self._power = value

            @property
            def temperature(self):                     # read through a property
                return self._temp

            def update(self, dt):
                self._temp += 0.1 * self._power * dt
    ''')
    from fmugen.__main__ import init
    _, data = init(tmp_path / "lab.py", tmp_path / "inferred.toml")
    assert data["outputs"] == {"temperature": {}}       # the property is found by inference
    (tmp_path / "fmugen.toml").write_text(textwrap.dedent('''
        [model]
        entry = "lab.py:Lab"
        call = "update"
        [time]
        dt = "step_size"
        [inputs]
        power = { start = 10.0, to = "call:heater" }
        [outputs]
        temperature = {}
    '''))
    fmu = adapter(make_fmu(tmp_path))
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 2.0, False) == OK
    assert fmu.get("temperature") == 22.0
