from fmi2 import Fmi2FMU, Fmi2Status
import pickle

def compute_balances_simplified(inputs):
    rho_air = 1.2
    Cp_air = 1010
    vfr_5 = inputs[8]
    vfr_8 = inputs[12]
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
        self.u0 = 0.0
        self.u1 = 0.0
        self.u2 = 0.0
        self.u3 = 0.0
        self.u4 = 0.0
        self.u5 = 0.0
        self.u6 = 0.0
        self.u7 = 0.0
        self.u8 = 0.0
        self.u9 = 0.0
        self.u10 = 0.0
        self.u11 = 0.0
        self.u12 = 0.0
        self.u13 = 0.0
        self.u14 = 0.0
        self.u15 = 0.0
        self.u16 = 0.0
        self.u17 = 0.0
        self.mass_balance = 0.0
        self.energy_balance = 0.0
        self.mdot_air_in = 0.0
        self.mdot_air_out = 0.0
        self.Q_in = 0.0
        self.Q_out = 0.0
        self._update_outputs()

    def serialize(self):
        state = tuple([getattr(self, name) for name in ['u0', 'u1', 'u2', 'u3', 'u4', 'u5', 'u6', 'u7', 'u8', 'u9', 'u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'mass_balance', 'energy_balance', 'mdot_air_in', 'mdot_air_out', 'Q_in', 'Q_out']])
        return Fmi2Status.ok, pickle.dumps(state)

    def deserialize(self, data):
        values = pickle.loads(data)
        for name, val in zip(['u0', 'u1', 'u2', 'u3', 'u4', 'u5', 'u6', 'u7', 'u8', 'u9', 'u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'mass_balance', 'energy_balance', 'mdot_air_in', 'mdot_air_out', 'Q_in', 'Q_out'], values):
            setattr(self, name, val)
        self._update_outputs()
        return Fmi2Status.ok

    def _update_outputs(self):
        input_values = [self.u0, self.u1, self.u2, self.u3, self.u4, self.u5, self.u6, self.u7, self.u8, self.u9, self.u10, self.u11, self.u12, self.u13, self.u14, self.u15, self.u16, self.u17]
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