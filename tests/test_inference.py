"""`fmugen init`: configs inferred from unmodified models."""
import textwrap
import tomllib

import pytest

from conftest import EXAMPLES
from fmugen.__main__ import init, isolated_imports
from fmugen.config import Config, InterfaceError, load_config, parse_call
from fmugen.interface import infer_config, render_toml


def infer(target, **kwargs):
    kwargs.setdefault("probe", True)   # these tests check what the probe call finds; tests/test_static.py: without
    with isolated_imports():
        return infer_config(target, **kwargs)


def test_function_returning_a_dict():
    data, _ = infer(EXAMPLES / "psychrometry" / "psychrometry.py")
    assert data["model"]["entry"] == "psychrometry.py:compute_balances_simplified"
    assert len(data["inputs"]) == 18
    assert list(data["outputs"]) == ["mass_balance", "energy_balance", "mdot_air_in", "mdot_air_out", "Q_in", "Q_out"]


def test_installed_class_with_time_argument():
    data, comments = infer("simple_pid:PID")
    assert data["time"] == {"dt": "step_size"}
    assert data["inputs"] == {"input_": {"start": 0.0}}
    # components and tunings are 3-tuples: arrays, one scalar per element in FMI 2
    assert data["outputs"] == {"y": {"from": "return"}, "components": {"dimensions": [3]},
                               "tunings": {"dimensions": [3]}}
    assert data["parameters"]["Kp"] == {"start": 1.0}
    assert "tunable" in comments[("parameters", "Kp")]
    assert comments[("model", "constants.output_limits")] == {"python": "(None, None)"}


def test_class_with_attributes_state_and_sources():
    data, _ = infer(EXAMPLES / "rc_building" / "rc_simulator" / "building_physics.py:Zone",
                    call="solve_energy", config_dir=EXAMPLES / "rc_building")
    assert data["model"]["entry"] == "rc_simulator/building_physics.py:Zone"
    assert data["model"]["sources"] == ["rc_simulator"]
    assert data["states"]["t_m_prev"]["next"] == "attr:t_m_next"
    assert "t_air" in data["outputs"] and "heating_demand" in data["outputs"]
    assert data["parameters"]["max_heating_energy_per_floor_area"] == {"start": float("inf")}


def test_rendered_config_round_trips(tmp_path):
    (tmp_path / "tank.py").write_text(textwrap.dedent('''
        """A leaky tank."""
        class Tank:
            def __init__(self, area=2.0, leak=0.1, limits=(0, 5)):
                self.area, self.leak, self.limits = area, leak, limits
                self.level = 1.0

            def step(self, inflow: float, dt=1.0):
                self.level += (inflow - self.leak * self.level) / self.area * dt
                self.overflow = self.level > self.limits[1]
                return self.level
    '''))
    output, data = init(tmp_path / "tank.py")
    text = output.read_text()
    assert tomllib.loads(text)["model"] == {"entry": "tank.py:Tank", "call": "step"}
    assert tomllib.loads(text)["parameters"]["limits"] == {"dimensions": [2], "start": [0.0, 5.0]}
    assert data["outputs"] == {"y": {"from": "return"}, "overflow": {"type": "Boolean"}}
    assert data["locals"] == {"level": {}}
    assert load_config(output).entry_name == "Tank"

    with pytest.raises(FileExistsError):
        init(tmp_path / "tank.py")


def test_ambiguous_module_needs_a_name(tmp_path):
    (tmp_path / "two.py").write_text("def a(x=1.0):\n    return x\n\ndef b(x=1.0):\n    return x\n")
    with pytest.raises(InterfaceError, match="cannot tell which"):
        infer(tmp_path / "two.py")
    data, _ = infer(f"{tmp_path / 'two.py'}:b")
    assert data["model"]["entry"] == "two.py:b"


def test_unknown_config_keys_are_rejected(tmp_path):
    with pytest.raises(InterfaceError, match="unknown key"):
        Config({"model": {"entry": "m.py:f"}, "inputs": {"x": {"strat": 1.0}}}, tmp_path)
    with pytest.raises(InterfaceError, match="entry"):
        Config({"model": {}}, tmp_path)


def test_render_toml_values():
    text = render_toml({"model": {"entry": "m.py:f"}, "inputs": {"x": {"start": float("-inf"), "unit": "degC"}}})
    assert tomllib.loads(text)["inputs"]["x"]["start"] == float("-inf")


def test_fmi3_infers_arrays_binary_and_float32(tmp_path):
    (tmp_path / "filt.py").write_text(textwrap.dedent('''
        import numpy as np

        class Filter:
            def __init__(self, weights=(0.5, 0.25, 0.25), tag=b"\x01"):
                self.weights = np.array(weights, dtype=np.float32)
                self.history = np.zeros(3)

            def step(self, u=0.0):
                self.history = np.roll(self.history, 1)
                self.history[0] = u
                self.out = np.float32(self.weights @ self.history)
                return self.history.copy()
    '''))
    data, comments = infer(tmp_path / "filt.py", fmi_version=3)
    assert data["model"]["fmi_version"] == 3
    assert data["parameters"]["weights"] == {"dimensions": [3], "start": [0.5, 0.25, 0.25]}
    assert data["parameters"]["tag"] == {"type": "Binary", "start": "01"}
    assert data["outputs"]["y"] == {"from": "return", "dimensions": [3]}
    assert data["outputs"]["out"] == {"type": "Float32"}
    assert "[clocks.sample]" in render_toml(data, comments)

    data2, comments2 = infer(tmp_path / "filt.py")              # FMI 2: arrays, but no Binary or Float32
    assert data2["parameters"]["weights"] == {"dimensions": [3], "start": [0.5, 0.25, 0.25]}
    assert "tag" not in data2["parameters"] and "--fmi 3" in comments2[("parameters", "#tag")]
    assert data2["outputs"]["out"] == {}


def test_start_setup_kind_and_errors(tmp_path):
    (tmp_path / "gh.py").write_text(textwrap.dedent('''
        STARTED = False

        def start():
            global STARTED
            STARTED = True

        class Filter:
            def __init__(self, x, g, h=0.1, **kwargs):
                if not STARTED:
                    raise RuntimeError("call start() first")
                self.x, self.g, self.h = x, g, h

            def update(self, z, g=None):
                self.x += (g or self.g) * (z - self.x)
                return self.x

        class Props:
            def __init__(self, **kwargs):
                self.T = kwargs["T"]
                self.double = 2 * kwargs["T"]
    '''))
    # g has no default in the constructor and one in update(): --start g goes to the constructor
    data, _ = infer(f"{tmp_path / 'gh.py'}:Filter", starts={"x": 0.0, "g": 0.5, "z": 1.0},
                    setup=["gh:start"])
    assert data["model"]["setup"] == ["gh:start"]
    assert data["parameters"]["g"] == {"start": 0.5} and data["inputs"]["z"] == {"start": 1.0}
    assert "g" not in data["inputs"] and data["outputs"] == {"y": {"from": "return"}}

    # a class whose constructor does the work, called like a function; inputs aren't echoed as outputs
    data, _ = infer(f"{tmp_path / 'gh.py'}:Props", kind="function", starts={"T": 300.0})
    assert data["model"]["kind"] == "function"
    assert data["inputs"] == {"T": {"start": 300.0}} and data["outputs"] == {"double": {}}

    with pytest.raises(InterfaceError, match="bytes need --fmi 3"):
        infer(f"{tmp_path / 'gh.py'}:Filter", starts={"x": b"", "g": 0.5})
    with pytest.raises(InterfaceError, match="not arguments"):
        infer(f"{tmp_path / 'gh.py'}:start", starts={"nope": 1.0})


@pytest.mark.parametrize("annotation", ["int | None", "Optional[int]", "typing.Optional[int]"])
def test_optional_annotation_keeps_the_type(tmp_path, annotation):
    (tmp_path / "opt.py").write_text(textwrap.dedent(f"""
        from __future__ import annotations
        import typing
        from typing import Optional
        def f(n: {annotation}, flag: bool | None, x: float | None) -> float:
            return 1.0
    """))
    data, _ = infer(tmp_path / "opt.py", probe=False)
    assert data["inputs"]["n"]["start"] == 0 and type(data["inputs"]["n"]["start"]) is int
    assert data["inputs"]["flag"]["start"] is False
    assert data["inputs"]["x"]["start"] == 0.0


def test_optional_from_typing_objects():
    import typing
    from fmugen.static import unwrap_optional
    assert unwrap_optional(typing.Optional[bool]) is bool
    assert unwrap_optional(int | None) is int
    assert unwrap_optional(int | str) == int | str


def test_number_like_outputs_are_kept(tmp_path):
    (tmp_path / "nums.py").write_text(textwrap.dedent("""
        from decimal import Decimal
        from fractions import Fraction
        import numpy
        def f(x: float = 1.0):
            return {"d": Decimal("1.5"), "q": Fraction(1, 3), "h": numpy.float16(2.0), "c": 1j}
    """))
    data, _ = infer(tmp_path / "nums.py")
    assert list(data["outputs"]) == ["d", "q", "h"]   # complex is not an FMI value


def test_pint_outputs_get_their_unit(tmp_path):
    pytest.importorskip("pint")
    (tmp_path / "q.py").write_text(textwrap.dedent("""
        import pint
        u = pint.get_application_registry()
        def f(x: float = 1.0):
            return {"v": u.Quantity(x, "m/s"), "n": u.Quantity(2.0, "")}
    """))
    data, _ = infer(tmp_path / "q.py")
    assert data["outputs"]["v"]["unit"] == "m/s"
    assert "unit" not in data["outputs"]["n"]


NESTED = """
from dataclasses import dataclass
from types import SimpleNamespace

@dataclass
class Zone:
    T: float
    occupied: bool

def f(x: float = 1.0):
    return {"zone": {"T": x, "air": {"rh": 0.5}}, "obj": Zone(2.0, True), "ns": SimpleNamespace(q=3.0)}
"""


def test_nested_outputs_are_named_with_dots(tmp_path):
    (tmp_path / "nested.py").write_text(NESTED)
    data, _ = infer(f"{tmp_path / 'nested.py'}:f")
    assert list(data["outputs"]) == ["zone.T", "zone.air.rh", "obj.T", "obj.occupied", "ns.q"]
    assert data["outputs"]["obj.occupied"]["type"] == "Boolean"
    static, _ = infer(f"{tmp_path / 'nested.py'}:f", probe=False)   # dict literals are read from the code too
    assert {"zone.T", "zone.air.rh"} <= set(static["outputs"])
    assert '"zone.air.rh" = {}' in render_toml(data)


def test_fmi3_time_attribute_is_renamed(tmp_path):
    (tmp_path / "clock.py").write_text(textwrap.dedent("""
        class M:
            def __init__(self):
                self.time = 0.0
            def step(self, dt: float = 1.0):
                self.time += dt
    """))
    data, _ = infer(tmp_path / "clock.py", fmi_version=3)
    assert "time" not in data.get("locals", {})
    assert data["locals"]["model_time"] == {"from": "attr:time"}


@pytest.mark.parametrize("kind", ["series", "frame", "xarray"])
def test_table_results_become_named_outputs(tmp_path, kind):
    pytest.importorskip("pandas")
    if kind == "xarray":
        pytest.importorskip("xarray")
    body = {
        "series": "pandas.Series({'p': x, 'q': 2 * x})",
        "frame": "pandas.DataFrame({'p': [x], 'q': [2 * x]})",
        "xarray": "__import__('xarray').Dataset({'p': x, 'q': 2 * x})",
    }[kind]
    (tmp_path / "table.py").write_text(f"import pandas\ndef f(x: float = 1.0):\n    return {body}\n")
    data, _ = infer(tmp_path / "table.py")
    assert data["outputs"] == {"p": {}, "q": {}}


OBJECT_ARGS = """
import dataclasses
from typing import Optional

@dataclasses.dataclass
class Weather:
    T: float
    windy: bool = False
    label: object = None

@dataclasses.dataclass
class Plant:
    gain: float = 2.0
    lag: int = 3
    notes: tuple = ("a",)

def f(w: Weather, plant: Plant = Plant(), opt: Optional[Weather] = None):
    return w.T * plant.gain
"""


def test_object_arguments_become_one_variable_per_field(tmp_path):
    (tmp_path / "objs.py").write_text(OBJECT_ARGS)
    data, comments = infer(f"{tmp_path / 'objs.py'}:f", starts={"w.T": 20.0})
    inputs = data["inputs"]
    assert inputs["w_T"] == {"start": 20.0, "to": "arg:w.T"}
    assert inputs["w_windy"] == {"start": False, "to": "arg:w.windy"}
    assert "w_label" not in inputs and "plant_notes" not in inputs   # not FMI values: defaults kept
    assert inputs["plant_gain"] == {"start": 2.0, "to": "arg:plant.gain"}
    assert inputs["plant_lag"] == {"start": 3, "to": "arg:plant.lag"}
    assert "opt_T" not in inputs   # defaults to None: stays "not given"
    assert data["outputs"] == {"y": {"from": "return"}}   # the probe call built both objects
    _, comments = infer(f"{tmp_path / 'objs.py'}:f", probe=False)
    assert "no default" in comments[("inputs", "w_T")]


@pytest.mark.parametrize("library", ["pydantic", "attrs"])
def test_pydantic_and_attrs_arguments(tmp_path, library):
    pytest.importorskip(library)
    source = {
        "pydantic": "import pydantic\nclass In(pydantic.BaseModel):\n    T: float\n    n: int = 2\n",
        "attrs": "import attrs\n@attrs.define\nclass In:\n    T: float\n    n: int = 2\n",
    }[library]
    (tmp_path / "m.py").write_text(source + "def f(u: In):\n    return u.T * u.n\n")
    data, _ = infer(f"{tmp_path / 'm.py'}:f", starts={"u.T": 1.5})
    assert data["inputs"] == {"u_T": {"start": 1.5, "to": "arg:u.T"}, "u_n": {"start": 2, "to": "arg:u.n"}}
    assert data["outputs"] == {"y": {"from": "return"}}



def test_int_results_are_real_with_a_note(tmp_path):
    (tmp_path / "m.py").write_text(textwrap.dedent("""
        def f(x: float = 1.0):
            return {"count": 3, "y": x}
    """))
    data, comments = infer(tmp_path / "m.py")
    assert data["outputs"]["count"] == {} and "Integer" in comments[("outputs", "count")]
    assert ("outputs", "y") not in comments


def test_setup_call_keeps_keyword_arguments():
    # setup = ["reset(seed=0)"] must seed the reset, not call reset() (Gymnasium envs)
    assert parse_call("reset(seed=0)") == {"call": "reset", "args": [], "kwargs": {"seed": 0}}
    assert parse_call("psychrolib:SetUnitSystem(psychrolib.SI, strict=True)") == {
        "call": "psychrolib:SetUnitSystem", "args": [{"ref": "psychrolib.SI"}], "kwargs": {"strict": True}}
    with pytest.raises(InterfaceError, match=r"\*\*kwargs"):
        parse_call("reset(**opts)")
