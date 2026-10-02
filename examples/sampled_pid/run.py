"""Drive out/sampled_pid.fmu as an FMI 3 importer that ticks the `sample` clock.

fmpy's simulate never ticks input clocks, so this script does it with fmpy's low-level
FMU3Slave: communication steps of 0.05 s, the PID clock ticking every 0.1 s, and a simple
first-order plant (dy/dt = u - y) closing the loop.

    uv run python examples/sampled_pid/run.py out/sampled_pid.fmu
"""
import shutil
import sys
import tempfile
from ctypes import c_double, c_int

from fmpy import read_model_description
from fmpy.fmi3 import FMU3Slave, fmi3ValueReference

fmu_path = sys.argv[1] if len(sys.argv) > 1 else "out/sampled_pid.fmu"
step, stop = 0.05, 2.0

unzipdir = tempfile.mkdtemp()
shutil.unpack_archive(fmu_path, unzipdir, "zip")
md = read_model_description(unzipdir)
vr = {v.name: v.valueReference for v in md.modelVariables}

fmu = FMU3Slave(guid=md.guid, unzipDirectory=unzipdir, modelIdentifier="unifmu", instanceName="pid")
fmu.instantiate(eventModeUsed=True)
try:
    fmu.enterInitializationMode(startTime=0.0)
    fmu.exitInitializationMode()                      # the FMU is now in event mode

    # ask the FMU for the clock's interval, as an importer does
    interval, qualifier = (c_double * 1)(), (c_int * 1)()
    fmu.getIntervalDecimal((fmi3ValueReference * 1)(vr["sample"]), interval, qualifier)
    interval = interval[0]

    y, t, next_tick = 0.0, 0.0, 0.0                   # plant output, time, next clock tick
    print(f"{'time':>5} {'measurement':>12} {'pid output':>11}")
    while t <= stop + 1e-9:
        if t >= next_tick - 1e-9:                     # the sample clock is due: tick it
            fmu.setFloat64([vr["measurement"]], [y])
            fmu.setClock([vr["sample"]], [True])
            fmu.updateDiscreteStates()                # runs pid(measurement, dt)
            next_tick += interval
        u = fmu.getFloat64([vr["output"]])[0]         # held between ticks
        print(f"{t:5.2f} {y:12.4f} {u:11.4f}")
        fmu.enterStepMode()
        fmu.doStep(t, step)
        y += (u - y) * step                           # the plant, explicit Euler
        t = round(t + step, 10)
        fmu.enterEventMode()
    fmu.terminate()
finally:
    fmu.freeInstance()
    shutil.rmtree(unzipdir, ignore_errors=True)
