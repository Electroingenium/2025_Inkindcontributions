
import os
import socket
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

NAMESPACE_URI = "urn:eium:opcua:fmu"
MODEL_FILE = "model.fmu"

# Paths inside this container (see docker-compose.yml)
CONT_MODEL_DIR = "/model"
CONT_RESULTS_PATH = "/results"


@st.cache_resource
def get_opc():
    c = OPCClient(OPCUA_ENDPOINT)
    c.connect()
    return c


@st.cache_resource
def opc_nodes(_c):
    """Return {"Inputs": {name: node}, "Outputs": {name: node}} as published by the OPC UA server."""
    ns_idx = _c.get_namespace_index(NAMESPACE_URI)
    objects = _c.get_objects_node()
    nodes = {}
    for folder_name in ("Inputs", "Outputs"):
        folder = objects.get_child([ua.QualifiedName(folder_name, ns_idx)])
        nodes[folder_name] = {ch.get_browse_name().Name: ch for ch in folder.get_children()}
    return nodes


@st.cache_resource
def docker_client():
    return docker.from_env()


def host_path(client, container_path, env_var):
    """Host path behind one of this container's bind mounts.

    FMU runs are sibling containers started through the Docker socket, so their
    bind mounts need host paths. These are read from this container's own
    mounts unless overridden with an environment variable.
    """
    if os.getenv(env_var):
        return os.getenv(env_var)
    me = client.containers.get(socket.gethostname())
    for mount in me.attrs["Mounts"]:
        if mount["Destination"] == container_path:
            return mount["Source"]
    raise RuntimeError(f"{container_path} is not mounted in this container and {env_var} is not set")

def list_active_runs(client: docker.DockerClient):
    return [ct for ct in client.containers.list(all=True) if FMU_NAME_BASE in (ct.name or "")]


def run_fmu_container(client, stop_time, step_size, start_time=0.0):
    host_model_dir = host_path(client, CONT_MODEL_DIR, "HOST_MODEL_DIR")
    host_results_dir = host_path(client, CONT_RESULTS_PATH, "HOST_RESULTS_DIR")

    # 👉 Generar un nombre único basado en la hora actual
    run_name = f"fmu-run-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    env = {
        "FMU_PATH": f"{CONT_MODEL_DIR}/{MODEL_FILE}",
        "RESULTS_DIR": CONT_RESULTS_PATH,
        "START_TIME": str(start_time),
        "STOP_TIME": str(stop_time),
        "STEP_SIZE": str(step_size),
        "OPCUA_ENDPOINT": OPCUA_ENDPOINT,
    }

    volumes = {
        host_model_dir:   {"bind": CONT_MODEL_DIR,    "mode": "ro"},
        host_results_dir: {"bind": CONT_RESULTS_PATH, "mode": "rw"},
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
    st.write("Model:")
    st.code(f"{CONT_MODEL_DIR}/{MODEL_FILE}")

client = get_opc()
dock   = docker_client()
nodes  = opc_nodes(client)

colL, colR = st.columns(2)

with colL:
    st.subheader("Outputs (OPC UA)")
    for n, nd in nodes["Outputs"].items():
        try:
            v = nd.get_value()
            st.metric(n, f"{v:.3f}" if isinstance(v, float) else str(v))
        except Exception:
            st.text(f"{n}: (NA)")

with colR:
    st.subheader("Inputs (OPC UA)")
    for n, nd in nodes["Inputs"].items():
        try:
            cur = nd.get_value()
            vtype = nd.get_data_type_as_variant_type()
        except Exception as e:
            st.text(f"{n}: (NA) {e}")
            continue
        if vtype == ua.VariantType.Boolean:
            newv = st.checkbox(n, value=bool(cur), key=f"sp-{n}")
        elif vtype == ua.VariantType.String:
            newv = st.text_input(n, value=str(cur), key=f"sp-{n}")
        elif vtype == ua.VariantType.Double:
            newv = st.number_input(n, value=float(cur), key=f"sp-{n}")
        else:
            newv = st.number_input(n, value=int(cur), step=1, key=f"sp-{n}")
        if st.button(f"Update {n}", key=f"btn-{n}"):
            try:
                nd.set_value(ua.Variant(newv, vtype))
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
        st.info("There is not 'last run' yet.")

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
st.subheader("📊 Results of the simulation FMU")

csv_path = "/results/simulation_outputs.csv"

if os.path.exists(csv_path):
    try:
        df = pd.read_csv(csv_path)
        st.success(f"Data loaded from `{csv_path}`")

        st.dataframe(df)

        numeric_cols = [col for col in df.columns if col != "time"]
        selected_vars = st.multiselect(
            "Select variable to plot:",
            numeric_cols,
            default=[n for n in nodes["Outputs"] if n in numeric_cols][:2]
        )

        if selected_vars:
            st.line_chart(df.set_index("time")[selected_vars])
        else:
            st.info("Select one or more variable to plot in the graph.")
    except Exception as e:
        st.error(f"Error loading the CSV: {e}")
else:
    st.warning("⚠️ The results file is not available yet. Run a simulation first.")
