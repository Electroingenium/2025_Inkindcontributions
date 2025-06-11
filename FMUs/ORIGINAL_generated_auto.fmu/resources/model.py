from fmi2 import Fmi2FMU, Fmi2Status
import pickle

def compute_balances_simplified(inputs):
    rho_air = 1.2
    Cp_air = 1010
    vfr_5 = inputs[8]
    vfr_8 = inputs[11]
    vfr_13 = inputs[17]
    temp_1 = inputs[3]
    temp_11 = inputs[16]
    mdot_air_5 = vfr_5 * rho_air
    mdot_air_8 = vfr_8 * rho_air
    mdot_air_13 = vfr_13 * rho_air
    mdot_air_in = mdot_air_5 + mdot_air_8
    mdot_air_out = mdot_air_13
    mass_balance = mdot_air_in - mdot_air_out
    Q_in = mdot_air_in * Cp_air * temp_1
    Q_out = mdot_air_out * Cp_air * temp_11
    energy_balance = Q_in - Q_out
    return [mass_balance, energy_balance, mdot_air_in, mdot_air_out, Q_in, Q_out]

class Model(Fmi2FMU):
    def __init__(self, reference_to_attr=None) -> None:
        super().__init__(reference_to_attr)
        self.regen_target_temp = 60.0
        self.regen_vfr_setpoint = 0.1
        self.regen_heater_power = 0.0
        self.temp_1 = 25.0
        self.RH_1 = 0.5
        self.vfr_1 = 0.1
        self.temp_3 = 25.0
        self.RH_3 = 0.5
        self.vfr_5 = 0.1
        self.temp_6 = 25.0
        self.RH_6 = 0.5
        self.vfr_8 = 0.1
        self.temp_9 = 25.0
        self.RH_9 = 0.5
        self.temp_10 = 25.0
        self.RH_10 = 0.5
        self.temp_11 = 25.0
        self.vfr_13 = 0.1
        self.mass_balance = 0.0
        self.energy_balance = 0.0
        self.mdot_air_in = 0.0
        self.mdot_air_out = 0.0
        self.Q_in = 0.0
        self.Q_out = 0.0
        self._update_outputs()

    def serialize(self):
        state = tuple([getattr(self, name) for name in ['regen_target_temp', 'regen_vfr_setpoint', 'regen_heater_power', 'temp_1', 'RH_1', 'vfr_1', 'temp_3', 'RH_3', 'vfr_5', 'temp_6', 'RH_6', 'vfr_8', 'temp_9', 'RH_9', 'temp_10', 'RH_10', 'temp_11', 'vfr_13', 'mass_balance', 'energy_balance', 'mdot_air_in', 'mdot_air_out', 'Q_in', 'Q_out']])
        return Fmi2Status.ok, pickle.dumps(state)

    def deserialize(self, data):
        values = pickle.loads(data)
        for name, val in zip(['regen_target_temp', 'regen_vfr_setpoint', 'regen_heater_power', 'temp_1', 'RH_1', 'vfr_1', 'temp_3', 'RH_3', 'vfr_5', 'temp_6', 'RH_6', 'vfr_8', 'temp_9', 'RH_9', 'temp_10', 'RH_10', 'temp_11', 'vfr_13', 'mass_balance', 'energy_balance', 'mdot_air_in', 'mdot_air_out', 'Q_in', 'Q_out'], values):
            setattr(self, name, val)
        self._update_outputs()
        return Fmi2Status.ok

    def _update_outputs(self):
        input_values = [self.regen_target_temp, self.regen_vfr_setpoint, self.regen_heater_power, self.temp_1, self.RH_1, self.vfr_1, self.temp_3, self.RH_3, self.vfr_5, self.temp_6, self.RH_6, self.vfr_8, self.temp_9, self.RH_9, self.temp_10, self.RH_10, self.temp_11, self.vfr_13]
        results = compute_balances_simplified(input_values)
        self.mass_balance = results[0]
        self.energy_balance = results[1]
        self.mdot_air_in = results[2]
        self.mdot_air_out = results[3]
        self.Q_in = results[4]
        self.Q_out = results[5]

    def do_step(self, current_time, step_size, no_step_prior):
        self._update_outputs()
        return Fmi2Status.ok