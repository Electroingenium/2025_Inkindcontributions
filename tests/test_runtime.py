"""The generated adapter, driven through its FMI 2 methods without UniFMU."""
import importlib.util
import textwrap
from pathlib import Path

import pytest
from conftest import EXAMPLES

from fmugen.__main__ import init, isolated_imports
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


def test_failing_computed_constant_is_an_initialization_error(tmp_path, make_fmu, adapter):
    write(tmp_path, "deriv.py", """
        def derivative(fun, x=0.5):
            return fun(x)
    """, """
        [model]
        entry = "deriv.py:derivative"
        [model.constants]
        fun = { call = "math:nosuch" }
        [inputs]
        x = { start = 0.5 }
        [outputs]
        y = { from = "return" }
    """)
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))   # instantiating doesn't compute constants
    assert fmu.fmi2SetupExperiment(0.0, None, None) == OK and fmu.fmi2EnterInitializationMode() == OK
    assert fmu.fmi2ExitInitializationMode() == ERROR
    message = fmu.logs[-1][2]
    assert "constants.fun = 'math:nosuch' failed" in message and "AttributeError" in message


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


def test_state_with_cloudpickle_when_pickle_fails(tmp_path, make_fmu, adapter):
    write(tmp_path, "lam.py", '''
        class Scaled:
            def __init__(self, k=2.0):
                self.f = lambda u: k * u            # pickle can't store a lambda; cloudpickle can
                self.total = 0.0

            def step(self, u=1.0):
                self.total += self.f(u)
                return {"total": self.total}
    ''')
    with isolated_imports():
        init(str(tmp_path / "lam.py"), probe=True)
    assert "save_state" not in (tmp_path / "fmugen.toml").read_text()
    fmu = adapter(make_fmu(tmp_path))
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    status, state = fmu.fmi2SerializeFmuState()
    assert status == OK and state[:1] == b"C"              # saved with cloudpickle
    assert fmu.fmi2DoStep(1.0, 1.0, False) == OK and fmu.get("total") == 4.0
    assert fmu.fmi2DeserializeFmuState(state) == OK
    assert fmu.fmi2DoStep(1.0, 1.0, False) == OK and fmu.get("total") == 4.0   # rolled back, then redone


def test_state_of_selected_attributes(tmp_path, make_fmu, adapter):
    write(tmp_path, "res.py", '''
        import threading

        class Accumulator:
            def __init__(self):
                self.lock = threading.Lock()        # a fixed resource: can't be pickled at all
                self.total = 0.0

            def step(self, u=1.0):
                with self.lock:
                    self.total += u
                return {"total": self.total}
    ''')
    with isolated_imports():
        _, data = init(str(tmp_path / "res.py"), probe=True)
    assert data["model"]["save_state"] == ["total"]
    text = (tmp_path / "fmugen.toml").read_text()
    assert "kept as they are on restore: lock" in text
    fmu_dir = make_fmu(tmp_path)
    assert 'canGetAndSetFMUstate="true"' in (fmu_dir / "modelDescription.xml").read_text()
    fmu = adapter(fmu_dir)
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK and fmu.get("total") == 1.0
    _status, state = fmu.fmi2SerializeFmuState()
    lock = fmu.engine.obj.lock
    assert fmu.fmi2DoStep(1.0, 1.0, False) == OK and fmu.get("total") == 2.0
    assert fmu.fmi2DeserializeFmuState(state) == OK
    assert fmu.engine.obj.lock is lock                     # the resource is kept, not replaced
    assert fmu.fmi2DoStep(1.0, 1.0, False) == OK and fmu.get("total") == 2.0   # rolled back, then redone


def test_unpicklable_attribute_that_changes_is_flagged(tmp_path):
    # a generator advances on every step: saving only `count` would restore it wrongly, so init
    # names the attribute it leaves out and asks to check it (or set save_state = false)
    write(tmp_path, "gen.py", '''
        class Counter:
            def __init__(self):
                self.it = (i for i in range(1000))   # generators can't be pickled
                self.count = -1

            def step(self):
                self.count = next(self.it)
    ''')
    with isolated_imports():
        _, data = init(str(tmp_path / "gen.py"), probe=True)
    assert data["model"]["save_state"] == ["count"]
    assert "kept as they are on restore: it. Check those don't change" in (tmp_path / "fmugen.toml").read_text()


def test_save_state_false(tmp_path, make_fmu, adapter):
    write(tmp_path, "m.py", "def f(u=1.0):\n    return {'y': u}\n", config='''
        [model]
        entry = "m.py:f"
        save_state = false
        [inputs]
        u = { start = 1.0 }
        [outputs]
        y = {}
    ''')
    fmu_dir = make_fmu(tmp_path)
    assert 'canGetAndSetFMUstate="false"' in (fmu_dir / "modelDescription.xml").read_text()


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
    _, data = init(tmp_path / "lab.py", tmp_path / "inferred.toml", probe=True)
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


def test_build_does_not_run_the_model(tmp_path, make_fmu):
    # like tclab: constructing the model needs hardware (or a network) that isn't there at build time
    write(tmp_path, "hw.py", '''
        RUNS = []

        class Heater:
            def __init__(self, port="COM3"):
                RUNS.append("constructed")
                raise RuntimeError(f"no device on {port}")

            def step(self, power=0.0):
                RUNS.append("stepped")
                return {"T": 20.0 + power}
    ''', config='''
        [model]
        entry = "hw.py:Heater"
        call = "step"
        save_state = false
        [parameters]
        port = { start = "COM3" }
        [inputs]
        power = { start = 0.0 }
        [outputs]
        T = { from = "return:T" }
    ''')
    fmu_dir = make_fmu(tmp_path)
    assert 'canGetAndSetFMUstate="false"' in (fmu_dir / "modelDescription.xml").read_text()


@pytest.mark.parametrize("text, expected", [("true", True), ("False", False), (" 1 ", True), ("0", False),
                                            ("yes", True), ("off", False)])
def test_boolean_from_strings(text, expected):
    from fmugen.templates.fmugen_runtime import coerce
    assert coerce("Boolean", text) is expected


def test_boolean_from_unknown_string_is_an_error():
    from fmugen.templates.fmugen_runtime import coerce
    with pytest.raises(ValueError):
        coerce("Boolean", "maybe")


def test_number_like_values_are_coerced():
    from decimal import Decimal
    from fractions import Fraction

    from fmugen.templates.fmugen_runtime import coerce, plain_number
    assert coerce("Real", plain_number(Decimal("1.5"))) == 1.5
    assert coerce("Real", plain_number(Fraction(1, 4))) == 0.25


def test_pint_quantities_in_and_out():
    pint = pytest.importorskip("pint")
    from fmugen.templates.fmugen_runtime import converter, plain_number
    q = converter({"convert": "pint", "unit": "kPa"})(100.0)
    assert q == pint.get_application_registry().Quantity(100.0, "kPa")
    assert plain_number(q, "Pa") == pytest.approx(1e5)
    assert plain_number(q) == 100.0


def test_dotted_paths_walk_mappings_sequences_and_attributes():
    from types import SimpleNamespace

    from fmugen.templates.fmugen_runtime import pick
    result = (0, {"rewards": {"speed": 1.5}, "a.b": 2}, SimpleNamespace(state={"T": 3}))
    assert pick(result, "1.rewards.speed") == 1.5
    assert pick(result[1], "a.b") == 2
    assert pick(result, "2.state.T") == 3


def test_nested_outputs_through_an_fmu(tmp_path, make_fmu, adapter):
    (tmp_path / "nested.py").write_text(textwrap.dedent("""
        def f(x: float = 1.0):
            return {"zone": {"T": 2 * x, "air": {"rh": 0.5}}}
    """))
    init(tmp_path / "nested.py", output=tmp_path / "fmugen.toml")
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))
    fmu.initialize()
    assert fmu.set("x", 3.0) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("zone.T", "zone.air.rh") == [6.0, 0.5]


def test_table_values_are_read_by_label():
    pandas = pytest.importorskip("pandas")
    from fmugen.templates.fmugen_runtime import coerce, pick, plain_number
    frame = pandas.DataFrame({"zenith": [33.3], "azimuth": [120.0]})
    assert coerce("Real", plain_number(pick(frame, "zenith"))) == 33.3
    assert coerce("Real", plain_number(pick(pandas.Series({"a": 1.5}), "a"))) == 1.5


def test_time_argument_with_an_epoch_is_a_datetime(tmp_path, make_fmu, adapter):
    (tmp_path / "clock.py").write_text(textwrap.dedent("""
        def hour(time):
            return {"hour": time.hour + time.minute / 60}
    """))
    (tmp_path / "fmugen.toml").write_text(textwrap.dedent("""
        [model]
        entry = "clock.py:hour"
        [time]
        time = { source = "end_time", epoch = "2026-06-21T06:00:00+00:00" }
        [outputs]
        hour = {}
    """))
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 5400.0, False) == OK
    assert fmu.get("hour") == 7.5


def test_epoch_must_be_a_date_time(tmp_path, make_fmu):
    from fmugen.config import InterfaceError
    (tmp_path / "clock.py").write_text("def hour(time):\n    return time\n")
    (tmp_path / "fmugen.toml").write_text(
        '[model]\nentry = "clock.py:hour"\n[time]\ntime = { epoch = "yesterday" }\n[outputs]\ny = { from = "return" }\n')
    with pytest.raises(InterfaceError, match="ISO 8601"):
        make_fmu(tmp_path / "fmugen.toml")


def test_object_argument_fields_through_an_fmu(tmp_path, make_fmu, adapter):
    (tmp_path / "objs.py").write_text(textwrap.dedent("""
        import dataclasses

        @dataclasses.dataclass(frozen=True)
        class Plant:
            gain: float = 2.0
            name: str = "p1"
            notes: tuple = ("kept",)

        @dataclasses.dataclass
        class Weather:
            T: float

        def f(w: Weather, plant: Plant = Plant()):
            assert plant.notes == ("kept",)          # a field that isn't a variable keeps its default
            return {"y": w.T * plant.gain}
    """))
    init(f"{tmp_path / 'objs.py'}:f", output=tmp_path / "fmugen.toml", starts={"w.T": 1.0})
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))
    fmu.initialize()
    assert fmu.set("w_T", 3.0) == OK and fmu.set("plant_gain", 4.0) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("y") == 12.0


def test_model_reads_data_files_by_relative_path(tmp_path, make_fmu, adapter, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "gain.txt").write_text("3.0")
    (tmp_path / "scaled.py").write_text(textwrap.dedent("""
        GAIN = float(open("data/gain.txt").read())        # read when imported

        def scaled(x: float = 1.0):
            with open("data/gain.txt") as f:               # and on every call
                return {"y": x * float(f.read()), "g": GAIN}
    """))
    init(tmp_path / "scaled.py")
    text = (tmp_path / "fmugen.toml").read_text()
    assert 'sources = ["data/gain.txt"]' in text and 'cwd = "."' in text
    fmu_dir = make_fmu(tmp_path / "fmugen.toml")
    monkeypatch.chdir(tmp_path.parent)                      # the importer runs somewhere else
    fmu = adapter(fmu_dir)
    fmu.initialize()
    assert fmu.set("x", 2.0) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("y", "g") == [6.0, 3.0]
    assert Path.cwd() == tmp_path.parent                   # and gets its working directory back


def test_cwd_must_be_a_folder_inside_the_project(tmp_path):
    from fmugen.config import Config, InterfaceError
    with pytest.raises(InterfaceError, match="not a folder"):
        Config({"model": {"entry": "m.py:f", "cwd": "nope"}}, tmp_path)
    with pytest.raises(InterfaceError, match="must be inside"):
        Config({"model": {"entry": "m.py:f", "cwd": ".."}}, tmp_path)


def test_dotted_path_reaches_methods_of_a_dict():
    from fmugen.templates.fmugen_runtime import get_path
    options = {"a": 1}
    assert get_path({"options": options}, "options.update") == options.update
    assert get_path({"keys": 5}, "keys") == 5   # a key wins over a method of the same name


COUNTER = """
CALLS = 0
SCALE = 2.0

def tick(x: float = 1.0):
    global CALLS
    CALLS += 1
    return {"y": x * SCALE, "calls": CALLS}
"""


def test_module_globals_are_reset_and_saved(tmp_path, make_fmu, adapter):
    (tmp_path / "counter.py").write_text(COUNTER)
    _, data = init(tmp_path / "counter.py")
    assert data["model"]["globals"] == ["counter:CALLS"]          # SCALE is never rebound
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))
    fmu.initialize()
    for t in range(3):
        assert fmu.fmi2DoStep(float(t), 1.0, False) == OK
    calls = fmu.get("calls")
    _status, state = fmu.fmi2SerializeFmuState()
    assert fmu.fmi2DoStep(3.0, 1.0, False) == OK and fmu.get("calls") == calls + 1
    assert fmu.fmi2DeserializeFmuState(state) == OK
    assert fmu.fmi2DoStep(3.0, 1.0, False) == OK and fmu.get("calls") == calls + 1   # rolled back first
    assert fmu.fmi2Reset() == OK
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("calls") == calls - 2   # counted from the import-time value again


def test_globals_must_exist(tmp_path, make_fmu):
    from fmugen.config import InterfaceError
    (tmp_path / "counter.py").write_text(COUNTER)
    (tmp_path / "fmugen.toml").write_text(
        '[model]\nentry = "counter.py:tick"\nglobals = ["counter:NOPE"]\n[outputs]\ny = {}\n')
    with pytest.raises(InterfaceError, match="NOPE"):
        make_fmu(tmp_path / "fmugen.toml")


def test_rollback_repeats_random_draws(tmp_path, make_fmu, adapter):
    (tmp_path / "noisy.py").write_text(textwrap.dedent("""
        import random
        import numpy as np

        def noisy(x: float = 0.0):
            return {"a": x + random.random(), "b": x + float(np.random.normal())}
    """))
    init(tmp_path / "noisy.py")
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))
    fmu.initialize()
    _, state = fmu.fmi2SerializeFmuState()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    first = fmu.get("a", "b")
    assert fmu.fmi2DeserializeFmuState(state) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("a", "b") == first



def test_star_args_constructor_gets_positional_parameters(tmp_path, make_fmu, adapter):
    write(tmp_path, "affine.py", """
        class Affine:
            def __init__(self, *args, **kwargs):   # e.g. control.StateSpace(A, B, C, D)
                self.a, self.b = args

            def step(self, x=1.0):
                return self.a * x + self.b
    """)
    output, data = init(tmp_path / "affine.py", starts={"a": 2.0, "b": 0.5})
    assert data["parameters"] == {"a": {"start": 2.0, "to": "pos:0"}, "b": {"start": 0.5, "to": "pos:1"}}
    fmu = adapter(make_fmu(output))
    assert fmu.set("a", 3.0) == OK
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("y") == 3.5


def test_star_args_constructor_and_method_split_by_the_probe(tmp_path, make_fmu, adapter):
    write(tmp_path, "normal.py", """
        import math

        class Normal:   # like SWIG's openturns.Normal(mu, sigma).computePDF(x)
            def __init__(self, *args):
                self.mu, self.sigma = args

            def pdf(self, *args):
                (x,) = args
                return math.exp(-((x - self.mu) / self.sigma) ** 2 / 2) / (self.sigma * math.sqrt(2 * math.pi))
    """)
    starts = {"mu": 0.0, "sigma": 1.0, "x": 0.5}
    output, data = init(f"{tmp_path / 'normal.py'}:Normal", call="pdf", starts=starts, probe=True)
    assert data["parameters"] == {"mu": {"start": 0.0, "to": "pos:0"}, "sigma": {"start": 1.0, "to": "pos:1"}}
    assert data["inputs"] == {"x": {"start": 0.5, "to": "pos:0"}}
    fmu = adapter(make_fmu(output))
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("y") == pytest.approx(0.3520653267642995)


def test_computed_constant_for_star_args(tmp_path, make_fmu, adapter):
    write(tmp_path, "affine.py", """
        class Affine:
            def __init__(self, *args):   # e.g. nashpy.Game(A)
                self.a, self.b = args

            def step(self, x=1.0):
                return self.a * x + self.b
    """)
    output, data = init(tmp_path / "affine.py", starts={"a": {"call": "math:sqrt(4.0)"}, "b": 0.5})
    assert data["model"]["constants"] == {"0": {"call": "math:sqrt(4.0)"}}
    assert data["parameters"] == {"b": {"start": 0.5, "to": "pos:1"}}
    assert '0 = { call = "math:sqrt(4.0)" }' in output.read_text()
    fmu = adapter(make_fmu(output))
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("y") == 2.5


def test_namedtuple_argument_fields(tmp_path, make_fmu, adapter):
    write(tmp_path, "meal.py", """
        from typing import NamedTuple

        class Action(NamedTuple):
            CHO: float
            insulin: float = 0.0

        class Patient:
            def __init__(self):
                self.glucose = 100.0

            def step(self, action: Action):
                self.glucose += action.CHO - 10 * action.insulin
                return self.glucose
    """)
    output, data = init(f"{tmp_path / 'meal.py'}:Patient", starts={"action.CHO": 1.0})
    assert data["inputs"]["action_CHO"] == {"start": 1.0, "to": "arg:action.CHO"}
    fmu = adapter(make_fmu(output))
    fmu.initialize()
    assert fmu.set("action_insulin", 0.5) == OK
    assert fmu.fmi2DoStep(0.0, 1.0, False) == OK
    assert fmu.get("y") == 96.0


def test_fields_of_an_argument_of_unknown_class_are_an_error(tmp_path):
    from fmugen.config import InterfaceError
    write(tmp_path, "kw.py", """
        class Patient:
            def __init__(self, **kwargs):
                pass

            def step(self, action):
                return action.CHO
    """)
    with pytest.raises(InterfaceError, match="cannot tell the class of action"):
        init(tmp_path / "kw.py", starts={"action.CHO": 1.0})


def test_date_time_argument_gets_an_epoch(tmp_path, make_fmu, adapter):
    write(tmp_path, "sun.py", """
        import datetime

        def altitude(lat=40.0, when: datetime.datetime | None = None):
            return {"hour": when.hour + when.minute / 60}
    """)
    output, data = init(tmp_path / "sun.py")
    assert "# a date-time argument: the epoch" in output.read_text()   # annotated: not a guess
    assert data["time"]["when"]["source"] == "end_time"
    assert data["time"]["when"]["epoch"].endswith("T00:00:00")
    fmu = adapter(make_fmu(output))
    fmu.initialize()
    assert fmu.fmi2DoStep(0.0, 5400.0, False) == OK
    assert fmu.get("hour") == 1.5


def test_string_in_a_real_output_says_to_set_its_type(tmp_path, make_fmu, adapter):
    write(tmp_path, "chem.py", """
        def chemical(T=300.0):
            return {"CAS": "7732-18-5"}
    """, config="""
        [model]
        entry = "chem.py:chemical"
        [outputs]
        CAS = {}
    """)
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))
    assert fmu.fmi2SetupExperiment(0.0, None, None) == OK and fmu.fmi2EnterInitializationMode() == OK
    assert fmu.fmi2ExitInitializationMode() == ERROR
    assert 'CAS is a string' in fmu.logs[-1][2] and 'set type = "String"' in fmu.logs[-1][2]


def test_no_outputs_is_a_warning_and_a_build_note(tmp_path, make_fmu, capsys):
    write(tmp_path, "quiet.py", """
        class Quiet:
            def step(self, x=1.0):
                self.update(x)

            def update(self, x):
                pass
    """)
    output, _ = init(tmp_path / "quiet.py")
    assert "no outputs found" in capsys.readouterr().err
    assert "no outputs found" in output.read_text()
    make_fmu(output)
    assert "the FMU has no outputs" in capsys.readouterr().out


def test_call_reaches_lazily_exported_submodules(tmp_path, monkeypatch):
    from fmugen.templates.fmugen_runtime import call_reference
    package = tmp_path / "lazypkg"
    (package / "models").mkdir(parents=True)
    (package / "__init__.py").write_text(textwrap.dedent("""
        def __getattr__(name):   # as pybamm exports lithium_ion
            if name == "family":
                from .models import family
                return family
            raise AttributeError(name)
    """))
    (package / "models" / "__init__.py").write_text("")
    (package / "models" / "family.py").write_text("def SPM(n=1):\n    return ('SPM', n)\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with isolated_imports():
        assert call_reference("lazypkg.family:SPM(n=2)") == ("SPM", 2)
        with pytest.raises(ModuleNotFoundError):
            call_reference("lazypkg.missing:SPM()")


def test_misspelled_field_and_unknown_argument_are_named(tmp_path):
    from fmugen.config import InterfaceError
    write(tmp_path, "objs.py", """
        import dataclasses

        @dataclasses.dataclass
        class Weather:
            T: float

        def f(w: Weather):
            return {"y": w.T}
    """)
    with pytest.raises(InterfaceError, match=r"w \(Weather\) has no field 'Tx'"):
        init(f"{tmp_path / 'objs.py'}:f", starts={"w.Tx": 1.0})
    with pytest.raises(InterfaceError, match=r"not arguments of the model: \['v.T'\]"):
        init(f"{tmp_path / 'objs.py'}:f", starts={"w.T": 1.0, "v.T": 1.0})


def test_probe_retries_a_date_time_in_utc(tmp_path):
    write(tmp_path, "sun.py", """
        def altitude(when):
            if when.tzinfo is None:
                raise ValueError("needs a time zone")
            return {"hour": when.hour}
    """)
    output, data = init(tmp_path / "sun.py", probe=True)
    assert data["time"]["when"]["epoch"].endswith("T00:00:00+00:00")
    text = output.read_text()
    assert "the probe worked with one, not with a number" in text and "epoch in UTC" in text
    assert data["outputs"]["hour"] == {}


def test_warning_names_only_outputs_of_unknown_type(tmp_path, capsys):
    write(tmp_path, "chem.py", """
        def lookup(name):
            return name.upper()

        class Chemical:
            def __init__(self):
                self.level = 1.0

            def step(self, dt=1.0):
                self.level += 0.5 * dt
                self.count = self.level * 2
                self.label = lookup("x")
                return self.level
    """)
    init(f"{tmp_path / 'chem.py'}:Chemical")
    err = capsys.readouterr().err
    assert "warning: label: type not shown by the code" in err
    assert "count" not in err and "y" not in err.split(":")[1]


def test_numeric_strings_still_become_numbers(tmp_path, make_fmu, adapter):
    write(tmp_path, "text.py", """
        def reading(x=1.0):
            return {"v": "2.5"}
    """, config="""
        [model]
        entry = "text.py:reading"
        [outputs]
        v = {}
    """)
    fmu = adapter(make_fmu(tmp_path / "fmugen.toml"))
    fmu.initialize()
    assert fmu.get("v") == 2.5


@pytest.mark.parametrize("body, kind, comment", [
    ("return {'y': when.hour}", "time", "the probe worked with one, not with a number"),
    ("return {'y': when * 2.0}", "inputs", "suggests a date-time, but the probe failed with one"),
    ("return {'y': len(str(when))}", "time", "taken as a date-time from its name 'when'"),
])
def test_probe_checks_a_date_time_guessed_from_the_name(tmp_path, body, kind, comment):
    write(tmp_path, "m.py", f"""
        def f(when):
            {body}
    """)
    output, data = init(tmp_path / "m.py", probe=True)
    assert "when" in data.get(kind, {}) and "when" not in data.get("time" if kind == "inputs" else "inputs", {})
    assert comment in output.read_text()


def test_call_arguments_can_be_calls_builtins_and_containers():
    import math
    import operator

    from fmugen.templates.fmugen_runtime import call_reference
    assert call_reference("operator:add(math.sqrt(16.0), -1)") == 3.0
    assert call_reference('builtins:list((float("inf"), math.pi))') == [math.inf, math.pi]
    assert call_reference("builtins:dict(a=math.floor(2.5), b={'k': [math.e]})") == {"a": 2, "b": {"k": [math.e]}}
    # without parentheses: the object itself (a function to pass, an enum member), not called
    assert call_reference("math:sin") is math.sin
    assert call_reference("operator:attrgetter") is operator.attrgetter
    with pytest.raises(ValueError, match="arguments must be"):
        call_reference("builtins:print(lambda: 0)")


def test_init_stops_when_a_computed_constant_fails(tmp_path):
    write(tmp_path, "deriv.py", """
        def derivative(fun, x=0.5):
            return fun(x)
    """)
    from fmugen.config import InterfaceError
    with pytest.raises(InterfaceError, match="constants.fun = call:math:nosuch fails: AttributeError"):
        init(tmp_path / "deriv.py", starts={"fun": {"call": "math:nosuch"}}, probe=True)
    _, data = init(tmp_path / "deriv.py", output="-", starts={"fun": {"call": "math:cos"}}, probe=True)
    assert data["outputs"] == {"y": {"from": "return"}}
