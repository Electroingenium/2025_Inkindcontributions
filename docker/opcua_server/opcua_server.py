from opcua import ua, Server
import os
import time

# Configuración
ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://0.0.0.0:4840")
NAMESPACE_URI = os.getenv("OPCUA_NAMESPACE", "urn:eium:opcua:fmu")

# Variables a exponer (puedes añadir/quitar según tu FMU)
VARS_READONLY = [
    "energy_balance", "mass_balance", "mdot_air_in", "mdot_air_out",
    "Q_in", "Q_out",
    "temp_1","temp_2","temp_3","temp_4","temp_5","temp_6","temp_7","temp_8","temp_9","temp_10","temp_11",
    "vfr_1","vfr_3","vfr_5","vfr_8","vfr_13",
    "RH_1","RH_3","RH_5","RH_6","RH_8","RH_9",
    "regen_heater_power"
]
# Setpoints / entradas escribibles desde UI/cliente
VARS_WRITABLE = ["regen_vfr_setpoint", "regen_target_temp"]

def main():
    server = Server()
    server.set_endpoint(ENDPOINT)
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    server.set_security_IDs(["Anonymous"])

    idx = server.register_namespace(NAMESPACE_URI)

    objects = server.get_objects_node()
    fmu_folder = objects.add_folder(idx, "FMU")

    nodes = {}

    # Crea nodos de solo lectura
    for name in VARS_READONLY:
        v = fmu_folder.add_variable(idx, name, 0.0, varianttype=ua.VariantType.Double)
        # por defecto lectura; no writable
        nodes[name] = v

    # Crea nodos escribibles (setpoints)
    for name in VARS_WRITABLE:
        v = fmu_folder.add_variable(idx, name, 0.0, varianttype=ua.VariantType.Double)
        v.set_writable()
        nodes[name] = v

    server.start()
    print(f"OPC UA server escuchando en {ENDPOINT}")
    try:
        while True:
            time.sleep(1)
    finally:
        server.stop()

if __name__ == "__main__":
    main()
