import streamlit as st
from opcua import Client as OPCClient, ua
import os
import time

OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")
NAMESPACE_URI = os.getenv("OPCUA_NAMESPACE", "urn:eium:opcua:fmu")

SHOW_VARS = [
    "energy_balance", "mass_balance",
    "mdot_air_in", "mdot_air_out",
    "Q_in", "Q_out",
    "temp_1","temp_5","temp_10",
    "vfr_1","vfr_5","vfr_13",
    "RH_1","RH_6","RH_9",
    "regen_heater_power"
]
SETPOINTS = ["regen_vfr_setpoint", "regen_target_temp"]

@st.cache_resource
def get_client():
    c = OPCClient(OPCUA_ENDPOINT)
    c.connect()
    return c

def get_node(client, name):
    root = client.get_root_node()
    idx = client.get_namespace_index(NAMESPACE_URI)
    return root.get_child([
        ua.QualifiedName("Objects", 0),
        ua.QualifiedName("FMU", idx),
        ua.QualifiedName(name, idx)
    ])

def main():
    st.title("FMU • OPC UA • EIUM (demo)")
    st.caption(OPCUA_ENDPOINT)

    client = get_client()

    cols = st.columns(2)
    with cols[0]:
        st.subheader("Lecturas")
        for name in SHOW_VARS:
            try:
                val = get_node(client, name).get_value()
                st.metric(label=name, value=f"{val:.3f}")
            except Exception:
                st.write(f"{name}: (no disponible)")

    with cols[1]:
        st.subheader("Setpoints")
        for name in SETPOINTS:
            node = get_node(client, name)
            try:
                current = float(node.get_value())
            except Exception:
                current = 0.0

            new_val = st.number_input(name, value=float(current))
            if st.button(f"Actualizar {name}", key=f"btn-{name}"):
                node.set_value(ua.Variant(float(new_val), ua.VariantType.Double))
                st.success("Enviado")

    st.divider()
    if st.button("Refrescar"):
        time.sleep(0.1)
        st.rerun()

if __name__ == "__main__":
    main()
