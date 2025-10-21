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

    # Variables principales (inicialmente a 0)
    variables = [
        "energy_balance","mass_balance","mdot_air_in","mdot_air_out","Q_in","Q_out",
        "regen_heater_power","regen_vfr_setpoint","regen_target_temp"
    ]

    for name in variables:
        var = fmu_obj.add_variable(idx, name, ua.Variant(0.0, ua.VariantType.Double))
        var.set_writable()  # <-- Muy importante: permitirá al cliente escribirlas

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
