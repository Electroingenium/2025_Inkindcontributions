import datetime
import time
import logging
from opcua import Server, ua

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

    # Registrar el namespace estándar que usa el cliente FMU y Streamlit
    uri = "urn:eium:opcua:fmu"
    idx = server.register_namespace(uri)

    # Crear el nodo raíz de objetos OPC UA
    objects = server.get_objects_node()

    # ==========================================================
    # 🔹 VARIABLES CALCULADAS (actualizables por el cliente FMU)
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
        node.set_writable(True)  # el cliente FMU debe poder escribir estos valores
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
    # 🔹 VARIABLES AUXILIARES (también escribibles desde Streamlit)
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
        node.set_writable(True)
        aux_nodes[name] = node

    # ==========================================================
    # 🚀 INICIO DEL SERVIDOR
    # ==========================================================
    server.start()
    logger.info("✅ OPC UA server started at opc.tcp://0.0.0.0:4840")
    logger.info(f"Namespace URI: {uri}")
    logger.info(f"Namespace index: {idx}")
    logger.info("Variables disponibles:")
    for name in list(calc_vars.keys()) + list(control_vars.keys()) + list(aux_vars.keys()):
        logger.info(f" - {name} (writable)")

    try:
        # Mantiene vivo el servidor y actualiza la variable energy_balance como prueba
        while True:
            now = datetime.datetime.now()
            new_val = 3000.0 + (now.second * 10)
            calc_nodes["energy_balance"].set_value(ua.Variant(new_val, ua.VariantType.Double))

            if now.second % 5 == 0:
                logger.info(f"[{now.strftime('%H:%M:%S')}] energy_balance={new_val:.2f}")

            time.sleep(1)

    finally:
        server.stop()
        logger.info("🛑 OPC UA Server stopped.")


if __name__ == "__main__":
    main()


