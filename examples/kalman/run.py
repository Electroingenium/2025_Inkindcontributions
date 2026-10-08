"""Drive out/kalman.fmu as an FMI 3 importer that ticks the `measurement` clock.

An object moves at 1 m/s. Every 0.1 s the filter predicts; every 0.3 s a noisy position
measurement arrives, so this script sets `z`, ticks the triggered clock `measurement`
and lets the FMU run KalmanFilter.update(z).

    uv run python examples/kalman/run.py out/kalman.fmu
"""
import random
import shutil
import sys
import tempfile

from fmpy import read_model_description
from fmpy.fmi3 import FMU3Slave

fmu_path = sys.argv[1] if len(sys.argv) > 1 else "out/kalman.fmu"
step, stop = 0.1, 5.0
random.seed(1)

unzipdir = tempfile.mkdtemp()
shutil.unpack_archive(fmu_path, unzipdir, "zip")
md = read_model_description(unzipdir)
vr = {v.name: v.valueReference for v in md.modelVariables}

fmu = FMU3Slave(guid=md.guid, unzipDirectory=unzipdir, modelIdentifier="unifmu", instanceName="kalman")
fmu.instantiate(eventModeUsed=True)
try:
    fmu.enterInitializationMode(startTime=0.0)
    fmu.exitInitializationMode()
    fmu.enterStepMode()

    print(f"{'time':>5} {'true pos':>9} {'measured':>9} {'est. pos':>9} {'est. vel':>9}")
    t, k = 0.0, 0
    while t < stop - 1e-9:
        fmu.doStep(t, step)                           # predict()
        t, k = round(t + step, 10), k + 1
        measured = ""
        if k % 3 == 0:                                # a measurement arrives: tick the clock
            z = t + random.gauss(0.0, 0.5)
            fmu.enterEventMode()
            fmu.setFloat64([vr["z"]], [z])
            fmu.setClock([vr["measurement"]], [True])
            fmu.updateDiscreteStates()                # update(z)
            fmu.enterStepMode()
            measured = f"{z:9.3f}"
        position, velocity = fmu.getFloat64([vr["x"]], nValues=2)
        print(f"{t:5.1f} {t:9.3f} {measured:>9} {position:9.3f} {velocity:9.3f}")
    fmu.terminate()
finally:
    fmu.freeInstance()
    shutil.rmtree(unzipdir, ignore_errors=True)
