# noinspection PyPep8

from fmpy import read_model_description, extract, fmi_info, dump
from fmpy.fmi2 import FMU2Slave
from fmpy.model_description import ModelDescription
import numpy as np
import pandas as pd

from fmpy.util import auto_interval
from fmpy.simulation import instantiate_fmu, Input, apply_start_values, has_start_value, settable_in_initialization_mode, settable_in_instantiated, Recorder, FMICallException, fmi2Discard, fmi2Terminated, fmi2LastSuccessfulTime
from time import time as current_time
from typing import Union, Any, Dict, Sequence, Callable
from fmpy.simulation import SimulationResult

def export_model_description(model_description: ModelDescription, filename: str):
    df = pd.DataFrame(columns=["name","causality","reference","start_value","description"])
    for i,variable in enumerate(model_description.modelVariables):
        df.loc[i,"name"] = variable.name
        df.loc[i,"causality"] = variable.causality
        df.loc[i,"reference"] = variable.valueReference
        df.loc[i,"start_value"] = variable.start   
        df.loc[i,"description"] = variable.description   

    assert filename.lower().endswith((".csv",".xls",".xlsx")),\
    f"Wrong file extension for saving model description, the expected formats are: '.csv' o '.xls' o '.xlsx', but got: '.{filename.rsplit('.')[-1]}'"

    if filename.lower().endswith(".csv"):        
        df.to_csv(filename,sep=';',index=False)        
    elif filename.lower().endswith(".xlsx"):
        df.to_excel(filename,sheet_name="model_description",index=False)

def simulateCS_custom(model_description: ModelDescription, 
               fmu, 
               start_time: Union[float, str] = None,
               stop_time: Union[float, str] = None,
               step_size: Union[float, str] = None, 
               relative_tolerance: Union[float, str] = None, 
               start_values: Dict[str, Any] = {}, 
               apply_default_start_values: bool = False, 
               input_signals: np.ndarray = None, 
               output: Sequence[str] = None, 
               output_interval: Union[float, str] = None, 
               timeout: Union[float, str] = None, 
               step_finished: Callable[[float, Recorder], bool] = None, 
               set_input_derivatives: bool = False, 
               use_event_mode: bool = False, 
               early_return_allowed: bool = False, 
               validate: bool = True, 
               initialize: bool = True, 
               terminate: bool = True, 
               set_stop_time: bool = True) -> SimulationResult:

    if set_input_derivatives and not model_description.coSimulation.canInterpolateInputs:
        raise Exception("Parameter set_input_derivatives is True but the FMU cannot interpolate inputs.")

    if output_interval is None:
        output_interval = auto_interval(stop_time - start_time)

    sim_start = current_time()

    is_fmi1 = model_description.fmiVersion == '1.0'
    is_fmi2 = model_description.fmiVersion == '2.0'

    input = Input(fmu=fmu, modelDescription=model_description, signals=input_signals, set_input_derivatives=set_input_derivatives)

    time = start_time

    if initialize:

        # initialize the model
        if is_fmi1:
            start_values = apply_start_values(fmu, model_description, start_values, settable=has_start_value)
            input.apply(time)
            fmu.initialize(tStart=time, stopTime=stop_time if set_stop_time else None)
        elif is_fmi2:
            fmu.setupExperiment(tolerance=relative_tolerance, startTime=time, stopTime=stop_time if set_stop_time else None)
            start_values = apply_start_values(fmu, model_description, start_values, settable=settable_in_instantiated)
            fmu.enterInitializationMode()
            start_values = apply_start_values(fmu, model_description, start_values, settable=settable_in_initialization_mode)
            input.apply(time)
            fmu.exitInitializationMode()
        else:
            start_values = apply_start_values(fmu, model_description, start_values, settable=settable_in_instantiated)
            fmu.enterInitializationMode(tolerance=relative_tolerance, startTime=time, stopTime=stop_time if set_stop_time else None)
            start_values = apply_start_values(fmu, model_description, start_values, settable=settable_in_initialization_mode)
            input.apply(time)
            fmu.exitInitializationMode()

            if use_event_mode:

                update_discrete_states = True

                while update_discrete_states:
                    update_discrete_states, terminate_simulation, _, _, _, _ = fmu.updateDiscreteStates()

                if terminate_simulation:
                    raise Exception("The FMU requested to terminate the simulation during initialization.")

                fmu.enterStepMode()

    if validate and len(start_values) > 0:
        raise Exception("The start values for the following variables could not be set: " +
                        ', '.join(start_values.keys()))

    recorder = Recorder(fmu=fmu, modelDescription=model_description, variableNames=output, interval=output_interval)

    n_steps = time / step_size

    terminate_simulation = False

    # simulation loop
    while True:
        recorder.sample(time)

        if timeout is not None and (current_time() - sim_start) > timeout:
            break

        if terminate_simulation or time >= stop_time:
            break

        input.apply(time)

        if is_fmi1:

            if time + step_size <= stop_time:
                fmu.doStep(currentCommunicationPoint=time, communicationStepSize=step_size)
                n_steps += 1
                time = n_steps * step_size
            else:
                fmu.doStep(currentCommunicationPoint=time, communicationStepSize=stop_time - time)
                time = stop_time

        elif is_fmi2:

            try:
                if time + step_size <= stop_time:
                    fmu.doStep(currentCommunicationPoint=time, communicationStepSize=step_size)
                    n_steps += 1
                    time = n_steps * step_size
                else:
                    fmu.doStep(currentCommunicationPoint=time, communicationStepSize=stop_time - time)
                    time = stop_time
            except FMICallException as e:
                if e.status == fmi2Discard:
                    terminated = fmu.getBooleanStatus(fmi2Terminated)
                    if terminated:
                        time = fmu.getRealStatus(fmi2LastSuccessfulTime)
                        recorder.sample(time)
                        break
                else:
                    raise e
        else:

            t_input_event = input.nextEvent(time)

            t_next = (n_steps + 1) * step_size

            input_event = t_next > t_input_event

            step_size = t_input_event - time if input_event else t_next - time

            event_encountered, terminate_simulation, early_return, last_successful_time = fmu.doStep(currentCommunicationPoint=time, communicationStepSize=step_size)

            if early_return and not early_return_allowed:
                raise Exception("FMU returned early from doStep() but Early Return is not allowed.")

            if early_return and last_successful_time < t_next:
                time = last_successful_time
            else:
                time = t_next
                n_steps += 1

            if use_event_mode and (input_event or event_encountered):

                recorder.sample(last_successful_time, force=True)

                fmu.enterEventMode()

                input.apply(last_successful_time, after_event=True)

                update_discrete_states = True

                while update_discrete_states and not terminate_simulation:
                    update_discrete_states, terminate_simulation, _, _, _, _ = fmu.updateDiscreteStates()

                if terminate_simulation:
                    break

                fmu.enterStepMode()

        if step_finished is not None and not step_finished(time, recorder):
            recorder.sample(time)
            break

    if terminate:
        fmu.terminate()

    return recorder.result()

if __name__ == '__main__':
    pass