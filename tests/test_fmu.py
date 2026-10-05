"""Built FMUs: modelDescription.xml validity, and real simulations through UniFMU."""
import shutil
import sys

import pytest
from fmpy import read_model_description, simulate_fmu
from fmpy.fmi2 import FMU2Slave
from fmpy.validation import validate_fmu

from conftest import EXAMPLES
from fmugen.__main__ import build

EXAMPLE_NAMES = ["psychrometry", "simple_pid", "rc_building"]


@pytest.fixture(scope="module")
def fmus(tmp_path_factory):
    out = tmp_path_factory.mktemp("fmus")
    return {
        name: build(EXAMPLES / name, out / f"{name}.fmu")[0]
        for name in EXAMPLE_NAMES
    }


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_model_description_is_valid(fmus, name):
    assert validate_fmu(str(fmus[name])) == []


def test_model_description_details(fmus):
    md = read_model_description(str(fmus["rc_building"]))
    assert md.coSimulation.canHandleVariableCommunicationStepSize is False
    assert md.coSimulation.canGetAndSetFMUstate is True
    assert md.defaultExperiment.stepSize == "3600.0"
    variables = {v.name: v for v in md.modelVariables}
    assert variables["c_m"].causality == "calculatedParameter"
    assert variables["t_set_heating"].variability == "tunable"
    assert (variables["t_m_prev"].causality, variables["t_m_prev"].initial) == ("local", "exact")
    assert variables["ventilation_efficiency"].max == "1.0"


def test_fixed_step_fmu_simulates_with_input_file(fmus):
    result = simulate_fmu(str(fmus["rc_building"]), input=_csv(EXAMPLES / "rc_building" / "weather.csv"),
                          stop_time=86400, output_interval=3600, output=["t_air", "heating_demand"])
    assert len(result) == 25
    assert result["heating_demand"][1:].max() > 0           # a cold night needs heating
    assert abs(result["t_air"][1:] - 20.0).max() < 1.0      # ... which keeps the zone near the set point


def test_tunable_parameter_and_rollback_through_unifmu(fmus, tmp_path):
    unzipdir = tmp_path / "pid"
    shutil.unpack_archive(fmus["simple_pid"], unzipdir, "zip")
    md = read_model_description(str(unzipdir))
    vr = {v.name: v.valueReference for v in md.modelVariables}
    fmu = FMU2Slave(guid=md.guid, unzipDirectory=str(unzipdir), modelIdentifier="unifmu", instanceName="pid")
    fmu.instantiate()
    try:
        fmu.setupExperiment(startTime=0.0)
        fmu.enterInitializationMode()
        fmu.exitInitializationMode()
        fmu.doStep(0.0, 0.1)
        state = fmu.getFMUState()
        fmu.doStep(0.1, 0.1)
        first = fmu.getReal([vr["output"]])
        fmu.setFMUState(state)
        fmu.doStep(0.1, 0.1)
        assert fmu.getReal([vr["output"]]) == first

        fmu.setReal([vr["Kp"]], [10.0])
        fmu.doStep(0.2, 0.1)
        assert fmu.getReal([vr["output"]])[0] == pytest.approx(10.0 + 0.5 * 0.3)
        fmu.terminate()
    finally:
        fmu.freeInstance()


def _csv(path):
    import numpy as np
    return np.genfromtxt(path, delimiter=",", names=True, dtype=None)
