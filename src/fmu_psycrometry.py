"""Simplified mass and energy balance of an air-based drying process."""

# === FMU interface (read by fmugen) ===
# Order must match the unpacking in compute_balances_simplified.
INPUTS = {
    "regen_target_temp":   {"start": 60.0, "unit": "degC"},
    "airCond_target_temp": {"start": 22.0, "unit": "degC"},
    "precool_target_temp": {"start": 18.0, "unit": "degC"},
    "temp_1":    {"start": 28.0, "unit": "degC"},
    "hum_rel_1": {"start": 50.0, "unit": "%"},
    "temp_3":    {"start": 26.0, "unit": "degC"},
    "hum_rel_3": {"start": 45.0, "unit": "%"},
    "temp_4":    {"start": 25.0, "unit": "degC"},
    "vfr_5":     {"start": 1.2,  "unit": "m3/s"},
    "temp_6":    {"start": 24.0, "unit": "degC"},
    "hum_rel_6": {"start": 40.0, "unit": "%"},
    "temp_7":    {"start": 23.0, "unit": "degC"},
    "vfr_8":     {"start": 0.8,  "unit": "m3/s"},
    "temp_9":    {"start": 22.0, "unit": "degC"},
    "hum_rel_9": {"start": 35.0, "unit": "%"},
    "temp_10":   {"start": 21.0, "unit": "degC"},
    "temp_11":   {"start": 20.0, "unit": "degC"},
    "vfr_13":    {"start": 1.7,  "unit": "m3/s"},
}

OUTPUTS = {
    "mass_balance":   {"unit": "kg/s"},
    "energy_balance": {"unit": "W"},
    "mdot_air_in":    {"unit": "kg/s"},
    "mdot_air_out":   {"unit": "kg/s"},
    "Q_in":           {"unit": "W"},
    "Q_out":          {"unit": "W"},
}


def step(**inputs):
    """FMU entry point: named inputs in, {output_name: value} out."""
    return compute_balances_simplified([inputs[name] for name in INPUTS])


def compute_balances_simplified(inputs):
    """
    Simplified mass and energy balance calculator for an air-based drying process.

    Parameters:
    - inputs: list of 18 values representing temperature, humidity and volumetric flow rates
      [regen_target_temp, airCond_target_temp, precool_target_temp,
       temp_1, hum_rel_1, temp_3, hum_rel_3, temp_4, vfr_5,
       temp_6, hum_rel_6, temp_7, vfr_8,
       temp_9, hum_rel_9, temp_10, temp_11, vfr_13]

    Returns:
    - Dictionary with mass flow rates, energy terms and balances
    """

    # Unpack inputs
    (regen_target_temp, airCond_target_temp, precool_target_temp,
     temp_1, hum_rel_1, temp_3, hum_rel_3, temp_4, vfr_5,
     temp_6, hum_rel_6, temp_7, vfr_8,
     temp_9, hum_rel_9, temp_10, temp_11, vfr_13) = inputs

    # Physical constants
    rho_air = 1.2      # [kg/m³] density of dry air
    Cp_air = 1010      # [J/kg·K] specific heat of dry air
    dH_evap = 2.45e6   # [J/kg] latent heat of vaporization (not used here, but available)

    # Mass flow rate of air at each key point
    mdot_air_5 = vfr_5 * rho_air
    mdot_air_8 = vfr_8 * rho_air
    mdot_air_13 = vfr_13 * rho_air

    # Mass balance (dry air)
    mdot_air_in = mdot_air_5 + mdot_air_8
    mdot_air_out = mdot_air_13
    mass_balance = mdot_air_in - mdot_air_out

    # Energy balance (sensible heat, dry air only)
    Q_in = mdot_air_in * Cp_air * temp_1
    Q_out = mdot_air_out * Cp_air * temp_11
    energy_balance = Q_in - Q_out

    return {
        "mass_balance": mass_balance,
        "energy_balance": energy_balance,
        "mdot_air_in": mdot_air_in,
        "mdot_air_out": mdot_air_out,
        "Q_in": Q_in,
        "Q_out": Q_out
    }

# Demo execution block
if __name__ == "__main__":
    example_inputs = [
        60, 22, 18,     # Setpoint temps
        28, 50, 26, 45, 25,  # temp/hum at points 1 to 4
        1.2,            # vfr_5
        24, 40, 23, 0.8,  # temp/hum 6-7 and vfr_8
        22, 35, 21, 20, 1.7  # temp/hum 9-11 and vfr_13
    ]

    result = compute_balances_simplified(example_inputs)
    print("Mass balance [kg/s]:", result["mass_balance"])
    print("Energy balance [W]:", result["energy_balance"])
    print("Air mass flow in [kg/s]:", result["mdot_air_in"])
    print("Air mass flow out [kg/s]:", result["mdot_air_out"])
    print("Sensible energy in [W]:", result["Q_in"])
    print("Sensible energy out [W]:", result["Q_out"])
