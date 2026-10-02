"""`fmugen init`: configs inferred from unmodified models."""
import textwrap
import tomllib

import pytest

from conftest import EXAMPLES
from fmugen.__main__ import init, isolated_imports
from fmugen.config import Config, InterfaceError, load_config
from fmugen.interface import infer_config, render_toml


def infer(target, **kwargs):
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
    assert data["outputs"] == {"y": {"from": "return"}}
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
    assert "# limits = { python = \"(0, 5)\" }" in text
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
