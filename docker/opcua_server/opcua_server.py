# from opcua import ua, Server
# import os

# ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://0.0.0.0:4840")
# NAMESPACE_URI = os.getenv("OPCUA_NAMESPACE", "urn:eium:opcua:fmu")

# def main():
#     server = Server()
#     server.set_endpoint(ENDPOINT)
#     server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
#     server.set_security_IDs(["Anonymous"])
#     idx = server.register_namespace(NAMESPACE_URI)
#     root = server.get_objects_node()
#     fmu_obj = root.add_object(idx, "FMU")
#     # 👉 Nodo raíz donde se cuelgan las variables
#     objects = server.get_objects_node()

#     # Dentro de tu método de setup del servidor
#     energy_balance = objects.add_variable(idx, "energy_balance", 3029.0)
#     mass_balance = objects.add_variable(idx, "mass_balance", 0.12)
#     mdot_air_in = objects.add_variable(idx, "mdot_air_in", 0.24)
#     mdot_air_out = objects.add_variable(idx, "mdot_air_out", 0.12)
#     Q_in = objects.add_variable(idx, "Q_in", 6059.0)
#     Q_out = objects.add_variable(idx, "Q_out", 3029.0)

#     temp_1 = objects.add_variable(idx, "temp_1", 18.3)
#     temp_5 = objects.add_variable(idx, "temp_5", 21.6)
#     temp_10 = objects.add_variable(idx, "temp_10", 24.1)
#     vfr_1 = objects.add_variable(idx, "vfr_1", 0.45)
#     vfr_5 = objects.add_variable(idx, "vfr_5", 0.50)
#     vfr_13 = objects.add_variable(idx, "vfr_13", 0.47)
#     RH_1 = objects.add_variable(idx, "RH_1", 0.53)
#     RH_6 = objects.add_variable(idx, "RH_6", 0.49)
#     RH_9 = objects.add_variable(idx, "RH_9", 0.51)

#     # Muy importante
#     for var in [energy_balance, mass_balance, mdot_air_in, mdot_air_out, Q_in, Q_out,
#                 temp_1, temp_5, temp_10, vfr_1, vfr_5, vfr_13, RH_1, RH_6, RH_9]:
#         var.set_writable()

#     server.start()
#     print(f"✅ OPC UA Server running at {ENDPOINT}")

#     try:
#         while True:
#             pass  # El servidor ya solo mantiene el namespace y espera actualizaciones
#     finally:
#         server.stop()
#         print("🛑 Server stopped")

# if __name__ == "__main__":
#     main()

import datetime
import time
import logging
from opcua import Server

# ==========================================================
# 🔧 CONFIGURACIÓN DEL SERVIDOR OPC UA
# ==========================================================

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("opcua_server")

    # Crear el servidor OPC UA
    server = Server()
    server.set_endpoint("opc.tcp://0.0.0.0:4840")
    server.set_server_name("EIUM_OPCUA_Server")

    # Registrar un namespace (espacio de nombres)
    uri = "http://eium-opcua.local/"
    idx = server.register_namespace(uri)

    # Crear el nodo raíz de objetos OPC UA
    objects = server.get_objects_node()

    # ==========================================================
    # 🔹 VARIABLES CALCULADAS (solo lectura)
    # ==========================================================
    calc_vars = {
        "energy_balance": 3029.0,
        "mass_balance": 0.12,
        "mdot_air_in": 0.24,
        "mdot_air_out": 0.12,
        "Q_in": 6059.0,
        "Q_out": 3029.0,
    }

    calc_nodes = {}
    for name, value in calc_vars.items():
        node = objects.add_variable(idx, name, value)
        node.set_writable(False)  # solo la FMU las puede actualizar
        calc_nodes[name] = node

    # ==========================================================
    # 🔹 VARIABLES DE CONTROL (escribibles desde Streamlit)
    # ==========================================================
    control_vars = {
        "regen_heater_power": 0.0,
        "regen_vfr_setpoint": 0.0,
        "regen_target_temp": 0.0,
    }

    control_nodes = {}
    for name, value in control_vars.items():
        node = objects.add_variable(idx, name, value)
        node.set_writable(True)
        control_nodes[name] = node

    # ==========================================================
    # 🔹 VARIABLES AUXILIARES (también escribibles)
    # ==========================================================
    aux_vars = {
        "temp_1": 18.3,
        "temp_5": 21.6,
        "temp_10": 24.1,
        "vfr_1": 0.45,
        "vfr_5": 0.50,
        "vfr_13": 0.47,
        "RH_1": 0.53,
        "RH_6": 0.49,
        "RH_9": 0.51,
    }

    aux_nodes = {}
    for name, value in aux_vars.items():
        node = objects.add_variable(idx, name, value)
        node.set_writable(True)  # la UI Streamlit puede modificar estos valores
        aux_nodes[name] = node

    # ==========================================================
    # 🚀 INICIO DEL SERVIDOR
    # ==========================================================
    server.start()
    logger.info("✅ OPC UA server started at opc.tcp://0.0.0.0:4840")
    logger.info(f"Namespace index: {idx}")
    logger.info("Variables disponibles:")

    for name in list(calc_vars.keys()) + list(control_vars.keys()) + list(aux_vars.keys()):
        logger.info(f" - {name}")

    try:
        # Bucle principal (puede servir para mantener vivo el servidor)
        while True:
            # Ejemplo opcional: simulación de actualización de energy_balance
            now = datetime.datetime.now()
            new_val = 3000.0 + (now.second * 10)
            calc_nodes["energy_balance"].set_value(new_val)

            # Mostrar valores actuales cada 5 segundos
            if now.second % 5 == 0:
                logger.info(f"[{now.strftime('%H:%M:%S')}] energy_balance={new_val:.2f}")

            time.sleep(1)

    finally:
        server.stop()
        logger.info("🛑 OPC UA Server stopped.")


if __name__ == "__main__":
    main()

