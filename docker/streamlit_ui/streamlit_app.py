
import os
import time
import streamlit as st
from opcua import Client as OPCClient, ua
import docker
from datetime import datetime
import pandas as pd

OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "simnet")
FMU_IMAGE = os.getenv("FMU_IMAGE", "fmu-client:latest")
FMU_NAME_BASE = os.getenv("FMU_CONTAINER_NAME_BASE", "fmu-run")

HOST_MODEL_PATH = os.getenv("HOST_FMU_PATH")
HOST_RESULTS_PATH = os.getenv("HOST_RESULTS_PATH")
CONT_MODEL_PATH = "/app/model.fmu"
CONT_RESULTS_PATH = "/results"

SHOW_VARS = [
    "energy_balance","mass_balance","mdot_air_in","mdot_air_out","Q_in","Q_out",
    "temp_1","temp_5","temp_10","vfr_1","vfr_5","vfr_13","RH_1","RH_6","RH_9","regen_heater_power"
]

SETPOINTS = [
    "regen_vfr_setpoint","regen_target_temp",
    "temp_1","temp_5","temp_10","vfr_1","vfr_5","vfr_13","RH_1","RH_6","RH_9"
]

@st.cache_resource
def get_opc():
    c = OPCClient(OPCUA_ENDPOINT)
    c.connect()
    return c

def node(c, name):
    try:
        # list all namespaces so we can find the correct index dynamically
        ns_array = c.get_namespace_array()
        ns_idx = None
        for i, ns in enumerate(ns_array):
            if "urn:eium:opcua:fmu" in ns:
                ns_idx = i
                break

        if ns_idx is None:
            st.warning(f"⚠️ Namespace 'urn:eium:opcua:fmu' not found in {ns_array}")
            return None

        return c.get_objects_node().get_child([ua.QualifiedName(name, ns_idx)])

    except Exception as e:
        st.warning(f"⚠️ Could not find node '{name}': {e}")
        return None



@st.cache_resource
def docker_client():
    return docker.from_env()

def list_active_runs(client: docker.DockerClient):
    return [ct for ct in client.containers.list(all=True) if FMU_NAME_BASE in (ct.name or "")]


def run_fmu_container(client, stop_time, step_size, start_time=0.0):
    if not HOST_MODEL_PATH or not os.path.isabs(HOST_MODEL_PATH):
        raise RuntimeError("HOST_FMU_PATH (ruta absoluta en el host) no está definida o no es absoluta")

    # 👉 Generar un nombre único basado en la hora actual
    run_name = f"fmu-run-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    env = {
        "FMU_PATH": CONT_MODEL_PATH,
        "RESULTS_DIR": CONT_RESULTS_PATH,
        "START_TIME": str(start_time),
        "STOP_TIME": str(stop_time),
        "STEP_SIZE": str(step_size),
        "OPCUA_ENDPOINT": OPCUA_ENDPOINT,
    }

    volumes = {
        HOST_MODEL_PATH:   {"bind": CONT_MODEL_PATH,   "mode": "ro"},
        HOST_RESULTS_PATH: {"bind": CONT_RESULTS_PATH, "mode": "rw"},
    }

    container = client.containers.run(
        FMU_IMAGE,
        name=run_name,
        detach=True,
        environment=env,
        network=DOCKER_NETWORK,
        volumes=volumes,
    )
    return container

def stop_container(client: docker.DockerClient, name_or_id: str):
    try:
        ct = client.containers.get(name_or_id)
        ct.stop(timeout=5)
        ct.remove()
        return True, f"Stopped and removed: {name_or_id}"
    except Exception as e:
        return False, str(e)

def tail_logs(container, n=200):
    try:
        raw = container.logs(tail=n).decode("utf-8", errors="ignore")
        return raw
    except Exception as e:
        return f"(no logs) {e}"

# --- UI ---
st.title("EIUM • FMU via OPC UA • Orchestrated")
st.caption(f"OPC UA: {OPCUA_ENDPOINT}  •  Docker network: {DOCKER_NETWORK}")

with st.sidebar:
    st.header("Simulation Params")
    START_TIME = st.number_input("START_TIME [s]", value=0.0, step=1.0, format="%.3f")
    STOP_TIME  = st.number_input("STOP_TIME [s]",  value=10.0, step=1.0, format="%.3f")
    STEP_SIZE  = st.number_input("STEP_SIZE [s]",  value=1.0, step=0.1, format="%.3f")
    st.write("Model path (mounted):")
    st.code(HOST_MODEL_PATH)
    st.write("Results dir (mounted):")
    st.code(HOST_RESULTS_PATH)

client = get_opc()
dock   = docker_client()

colL, colR = st.columns(2)

with colL:
    st.subheader("Read variables (OPC UA)")
    for n in SHOW_VARS:
        try:
            v = float(node(client, n).get_value())
            st.metric(n, f"{v:.3f}")
        except Exception:
            st.text(f"{n}: (NA)")

with colR:
    st.subheader("Setpoints (OPC UA)")
    for n in SETPOINTS:
        nd = node(client, n)
        try:
            cur = float(nd.get_value())
        except Exception:
            cur = 0.0
        newv = st.number_input(n, value=float(cur), key=f"sp-{n}")
        if st.button(f"Actualizar {n}", key=f"btn-{n}"):
            try:
                nd.set_value(ua.Variant(float(newv), ua.VariantType.Double))
                st.success(f"{n} = {newv}")
            except Exception as e:
                st.error(f"Error: {e}")

st.divider()
st.subheader("Run FMU (docker)")

c1, c2, c3 = st.columns(3)
if c1.button("▶️ Run"):
    try:
        ct = run_fmu_container(dock, stop_time=STOP_TIME, step_size=STEP_SIZE, start_time=START_TIME)
        st.success(f"Launched: {ct.name}")
        st.session_state["last_run"] = ct.name
        time.sleep(0.5)
        st.rerun()
    except Exception as e:
        st.error(f"Run error: {e}")

if c2.button("⏹ Stop last"):
    last = st.session_state.get("last_run")
    if last:
        ok, msg = stop_container(dock, last)
        st.write(msg if ok else f"Stop error: {msg}")
    else:
        st.info("No hay 'last run' todavía.")

if c3.button("🔄 Refresh"):
    time.sleep(0.2)
    st.rerun()

st.markdown("### Active/Recent Runs")
runs = list_active_runs(dock)
if not runs:
    st.write("(no runs yet)")
else:
    for ct in runs:
        with st.expander(f"{ct.name}  •  status: {ct.status}"):
            st.code(tail_logs(ct, n=200))
            cols = st.columns(3)
            if cols[0].button(f"⏹ Stop {ct.name}", key=f"stop-{ct.name}"):
                ok, msg = stop_container(dock, ct.name)
                st.write(msg if ok else f"Stop error: {msg}")
            if cols[1].button(f"🔁 Refresh {ct.name}", key=f"ref-{ct.name}"):
                st.rerun()
            if cols[2].button(f"🧹 Remove {ct.name}", key=f"rm-{ct.name}"):
                try:
                    ct.remove(force=True)
                    st.success(f"Removed {ct.name}")
                except Exception as e:
                    st.error(f"Remove error: {e}")

st.markdown("---")
st.subheader("📊 Resultados de la simulación FMU")

csv_path = "/results/simulation_outputs.csv"

if os.path.exists(csv_path):
    try:
        df = pd.read_csv(csv_path)
        st.success(f"Datos cargados correctamente desde `{csv_path}`")

        st.dataframe(df)

        numeric_cols = [col for col in df.columns if col != "time"]
        selected_vars = st.multiselect(
            "Selecciona las variables a graficar",
            numeric_cols,
            default=["energy_balance", "mass_balance"]
        )

        if selected_vars:
            st.line_chart(df.set_index("time")[selected_vars])
        else:
            st.info("Selecciona una o más variables para visualizar la gráfica.")
    except Exception as e:
        st.error(f"Error al cargar el CSV: {e}")
else:
    st.warning("⚠️ El archivo de resultados no se ha encontrado aún. Ejecuta la simulación primero.")
