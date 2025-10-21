from opcua import ua, Server
import os

ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://0.0.0.0:4840")
NAMESPACE_URI = os.getenv("OPCUA_NAMESPACE", "urn:eium:opcua:fmu")

def main():
    server = Server()
    server.set_endpoint(ENDPOINT)
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    server.set_security_IDs(["Anonymous"])
    idx = server.register_namespace(NAMESPACE_URI)
    root = server.get_objects_node()
    fmu_obj = root.add_object(idx, "FMU")
    # 👉 Nodo raíz donde se cuelgan las variables
    objects = server.get_objects_node()

    # # Variables principales (inicialmente a 0)
    # variables = [
    #     "energy_balance","mass_balance","mdot_air_in","mdot_air_out","Q_in","Q_out",
    #     "regen_heater_power","regen_vfr_setpoint","regen_target_temp"
    # ]

    # for name in variables:
    #     var = fmu_obj.add_variable(idx, name, ua.Variant(0.0, ua.VariantType.Double))
    #     var.set_writable()  # <-- Muy importante: permitirá al cliente escribirlas

        # Dentro de tu método de setup del servidor
    energy_balance = objects.add_variable(idx, "energy_balance", 3029.0)
    mass_balance = objects.add_variable(idx, "mass_balance", 0.12)
    mdot_air_in = objects.add_variable(idx, "mdot_air_in", 0.24)
    mdot_air_out = objects.add_variable(idx, "mdot_air_out", 0.12)
    Q_in = objects.add_variable(idx, "Q_in", 6059.0)
    Q_out = objects.add_variable(idx, "Q_out", 3029.0)

    temp_1 = objects.add_variable(idx, "temp_1", 18.3)
    temp_5 = objects.add_variable(idx, "temp_5", 21.6)
    temp_10 = objects.add_variable(idx, "temp_10", 24.1)
    vfr_1 = objects.add_variable(idx, "vfr_1", 0.45)
    vfr_5 = objects.add_variable(idx, "vfr_5", 0.50)
    vfr_13 = objects.add_variable(idx, "vfr_13", 0.47)
    RH_1 = objects.add_variable(idx, "RH_1", 0.53)
    RH_6 = objects.add_variable(idx, "RH_6", 0.49)
    RH_9 = objects.add_variable(idx, "RH_9", 0.51)

    # Muy importante
    for var in [energy_balance, mass_balance, mdot_air_in, mdot_air_out, Q_in, Q_out,
                temp_1, temp_5, temp_10, vfr_1, vfr_5, vfr_13, RH_1, RH_6, RH_9]:
        var.set_writable()

    server.start()
    print(f"✅ OPC UA Server running at {ENDPOINT}")

    try:
        while True:
            pass  # El servidor ya solo mantiene el namespace y espera actualizaciones
    finally:
        server.stop()
        print("🛑 Server stopped")

if __name__ == "__main__":
    main()
