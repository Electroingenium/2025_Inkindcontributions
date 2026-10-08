"""Dashboard: edit inputs and watch outputs over OPC UA, launch FMU runs, plot their results.

Runs are started through one of two backends (RUN_BACKEND):
- docker: a sibling container through the Docker socket (docker compose)
- kubernetes: a Job in this pod's namespace; with Liqo it can be placed on a virtual node,
  i.e. run in a peered cluster, while this UI and the OPC UA server stay here.
Either way the results come back in the run's log (see fmu_runner.py).
"""
import io
import os
import secrets
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from fmu_io import NAMESPACE_URI, RESULTS_BEGIN, RESULTS_END, experiment, read_fmu
from opcua import Client as OPCClient
from opcua import ua

OPCUA_ENDPOINT = os.getenv("OPCUA_ENDPOINT", "opc.tcp://opcua-server:4840")
RUN_BACKEND = os.getenv("RUN_BACKEND", "docker")
FMU_IMAGE = os.getenv("FMU_IMAGE", "")
RUN_PREFIX = os.getenv("FMU_CONTAINER_NAME_BASE", "fmu-run")
STEP_DELAY = os.getenv("STEP_DELAY", "0.5")
FMU_PATH = os.getenv("FMU_PATH", "/model/model.fmu")
RUN_LABEL = "fmugen.run"


# ---------------------------------------------------------------- run backends

class DockerRuns:
    """Runs as sibling containers, started through the mounted Docker socket."""

    def __init__(self):
        import docker
        self.client = docker.from_env()
        self.network = os.getenv("DOCKER_NETWORK", "simnet")
        self.image = FMU_IMAGE or "fmugen-sim:latest"
        self.where = f"Docker network {self.network}"

    def start(self, name, env, placement=None):
        self.client.containers.run(self.image, ["python", "fmu_runner.py"], name=name, detach=True,
                                   environment=env, network=self.network, labels={RUN_LABEL: name})

    def list(self):
        """[(name, status)], newest first."""
        cts = self.client.containers.list(all=True, filters={"label": RUN_LABEL})
        return sorted(((ct.name, ct.status) for ct in cts), reverse=True)

    def logs(self, name):
        return self.client.containers.get(name).logs().decode("utf-8", errors="replace")

    def remove(self, name):
        self.client.containers.get(name).remove(force=True)


class KubernetesRuns:
    """Runs as Jobs in this pod's namespace. With Liqo, `remote` places them on virtual nodes."""

    PLACEMENTS = ("remote", "local", "any")
    VIRTUAL_NODE = {"key": "liqo.io/type", "values": ["virtual-node"]}

    def __init__(self):
        from kubernetes import client, config
        config.load_incluster_config()
        self.batch = client.BatchV1Api()
        self.core = client.CoreV1Api()
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace") as f:
            self.namespace = f.read().strip()
        # Same image as this pod unless FMU_IMAGE says otherwise
        me = self.core.read_namespaced_pod(os.environ["POD_NAME"], self.namespace)
        self.image = FMU_IMAGE or me.spec.containers[0].image
        self.pull_policy = me.spec.containers[0].image_pull_policy
        self.where = f"Kubernetes namespace {self.namespace}"

    def _affinity(self, placement):
        if placement not in ("remote", "local"):
            return None
        op = "In" if placement == "remote" else "NotIn"
        term = {"matchExpressions": [{**self.VIRTUAL_NODE, "operator": op}]}
        return {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [term]}}}

    def start(self, name, env, placement="remote"):
        pod_spec = {
            "restartPolicy": "Never",
            "containers": [{
                "name": "fmu-runner",
                "image": self.image,
                "imagePullPolicy": self.pull_policy,
                "command": ["python", "fmu_runner.py"],
                "env": [{"name": k, "value": v} for k, v in env.items()],
            }],
        }
        affinity = self._affinity(placement)
        if affinity:
            pod_spec["affinity"] = affinity
        job = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "labels": {RUN_LABEL: name}},
            "spec": {
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": 3600,
                "template": {"metadata": {"labels": {RUN_LABEL: name}}, "spec": pod_spec},
            },
        }
        self.batch.create_namespaced_job(self.namespace, job)

    def _pod(self, name):
        pods = self.core.list_namespaced_pod(self.namespace, label_selector=f"job-name={name}").items
        return pods[0] if pods else None

    def list(self):
        runs = []
        for job in self.batch.list_namespaced_job(self.namespace, label_selector=RUN_LABEL).items:
            s = job.status
            status = "succeeded" if s.succeeded else "failed" if s.failed else "running" if s.active else "pending"
            pod = self._pod(job.metadata.name)
            if pod is not None and pod.spec.node_name:
                status += f" on {pod.spec.node_name}"
            runs.append((job.metadata.name, status))
        return sorted(runs, reverse=True)

    def logs(self, name):
        pod = self._pod(name)
        if pod is None:
            return "(no pod yet)"
        # No log until the container starts; asking earlier is an API error
        for status in pod.status.container_statuses or []:
            if status.state.waiting:
                waiting = status.state.waiting
                return f"(starting: {waiting.reason}{f' - {waiting.message}' if waiting.message else ''})"
        if pod.status.phase == "Pending":
            return "(starting: waiting to be scheduled)"
        try:
            # raw response: the client would otherwise turn the bytes into "b'...'" text
            resp = self.core.read_namespaced_pod_log(pod.metadata.name, self.namespace, _preload_content=False)
            return resp.data.decode("utf-8", errors="replace")
        except Exception as e:
            return f"(no logs yet) {getattr(e, 'reason', None) or e}"

    def remove(self, name):
        self.batch.delete_namespaced_job(name, self.namespace, propagation_policy="Background")


# ---------------------------------------------------------------- helpers

@st.cache_resource
def _opc_session():
    """Connected client and {"Inputs": {name: node}, "Outputs": {name: node}} from the OPC UA server."""
    c = OPCClient(OPCUA_ENDPOINT, timeout=5)
    c.connect()
    ns_idx = c.get_namespace_index(NAMESPACE_URI)
    objects = c.get_objects_node()
    nodes = {}
    for folder_name in ("Inputs", "Outputs"):
        folder = objects.get_child([ua.QualifiedName(folder_name, ns_idx)])
        nodes[folder_name] = {ch.get_browse_name().Name: ch for ch in folder.get_children()}
    return c, nodes


def opc_session():
    """The cached session, reconnected if the server went away (e.g. its pod restarted)."""
    c, nodes = _opc_session()
    try:
        c.get_node(ua.ObjectIds.Server_ServerStatus_State).get_value()
    except Exception:
        try:
            c.disconnect()
        except Exception:
            pass
        _opc_session.clear()
        c, nodes = _opc_session()
    return c, nodes


@st.cache_resource
def fmu_info():
    """The FMU's description and default experiment (runs use this same image's FMU)."""
    md, _, _ = read_fmu(FMU_PATH)
    return md, experiment(md)


@st.cache_resource
def get_runs():
    return KubernetesRuns() if RUN_BACKEND == "kubernetes" else DockerRuns()


def results_from_logs(logs):
    """The results CSV a finished run printed, as a DataFrame, or None."""
    if RESULTS_END not in logs:
        return None
    csv = logs.split(RESULTS_BEGIN, 1)[1].split(RESULTS_END, 1)[0]
    return pd.read_csv(io.StringIO(csv.strip("\n")))


def show_value(name, value):
    if isinstance(value, list):
        st.text(f"{name}: {value}")
    else:
        st.metric(name, f"{value:.3f}" if isinstance(value, float) else str(value))


def parse_item(text, vtype):
    """One element of an edited array, typed like the OPC UA variable."""
    if vtype == ua.VariantType.Boolean:
        lowered = text.strip().lower()
        if lowered not in ("true", "false", "1", "0"):
            raise ValueError(f"{text!r} is not a Boolean: use true/false or 1/0")
        return lowered in ("true", "1")
    if vtype in (ua.VariantType.Double, ua.VariantType.Float):
        return float(text)
    return int(text)


def edit_value(name, value, vtype):
    key = f"sp-{name}"
    if isinstance(value, list):
        if vtype == ua.VariantType.String:   # strings may contain spaces: one per line
            items = st.text_area(f"{name} (one per line)", value="\n".join(value), key=key).split("\n")
        else:
            text = st.text_input(f"{name} (space-separated)", value=" ".join(map(str, value)), key=key)
            items = [parse_item(x, vtype) for x in text.split()]
        if len(items) != len(value):   # the FMU's array has a fixed size
            raise ValueError(f"needs {len(value)} values, got {len(items)}")
        return items
    if vtype == ua.VariantType.Boolean:
        return st.checkbox(name, value=bool(value), key=key)
    if vtype == ua.VariantType.String:
        return st.text_input(name, value=str(value), key=key)
    if vtype in (ua.VariantType.Double, ua.VariantType.Float):
        return st.number_input(name, value=float(value), key=key)
    return st.number_input(name, value=int(value), step=1, key=key)


# ---------------------------------------------------------------- UI

st.title("EIUM • FMU via OPC UA • Orchestrated")

runs = get_runs()
md, (start0, stop0, step0, fixed_step) = fmu_info()
st.caption(f"Model: {md.modelName} (FMI {md.fmiVersion})  •  OPC UA: {OPCUA_ENDPOINT}  •  "
           f"Runs: {runs.where}  •  Image: {runs.image}")

with st.sidebar:
    st.header("Simulation Params")
    START_TIME = st.number_input("START_TIME [s]", value=start0, step=1.0, format="%.3f")
    STOP_TIME = st.number_input("STOP_TIME [s]", value=stop0, step=1.0, format="%.3f")
    STEP_SIZE = st.number_input("STEP_SIZE [s]", value=step0, step=0.1, format="%.3f", disabled=fixed_step,
                                help="This FMU only takes steps of its default size" if fixed_step else None)
    placement = None
    if RUN_BACKEND == "kubernetes":   # not isinstance: reruns redefine the class, the cached object keeps the old one
        default = os.getenv("RUN_PLACEMENT", "remote")
        placement = st.radio(
            "Run on", KubernetesRuns.PLACEMENTS, index=KubernetesRuns.PLACEMENTS.index(default),
            help="remote: a Liqo virtual node (a peered cluster); local: this cluster's own nodes; any: either",
        )

client, nodes = opc_session()

colL, colR = st.columns(2)

with colL:
    st.subheader("Outputs (OPC UA)")
    for n, nd in nodes["Outputs"].items():
        try:
            show_value(n, nd.get_value())
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
        try:
            newv = edit_value(n, cur, vtype)
        except ValueError as e:
            st.error(f"{n}: {e}")
            continue
        if st.button(f"Update {n}", key=f"btn-{n}"):
            try:
                nd.set_value(ua.Variant(newv, vtype))
                st.success(f"{n} = {newv}")
            except Exception as e:
                st.error(f"Error: {e}")

st.divider()
st.subheader("Run FMU")

c1, c2 = st.columns(2)
if c1.button("▶️ Run"):
    # timestamp sorts newest first; the suffix keeps two runs in the same second apart
    name = f"{RUN_PREFIX}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"
    env = {
        "RUN_NAME": name,
        "START_TIME": str(START_TIME),
        "STOP_TIME": str(STOP_TIME),
        "STEP_SIZE": str(STEP_SIZE),
        "STEP_DELAY": STEP_DELAY,
        "OPCUA_ENDPOINT": OPCUA_ENDPOINT,
    }
    try:
        runs.start(name, env, placement)
        st.session_state["last_run"] = name
        st.success(f"Launched: {name}")
        time.sleep(0.5)
        st.rerun()
    except Exception as e:
        st.error(f"Run error: {e}")

if c2.button("🔄 Refresh"):
    st.rerun()

st.markdown("### Runs")
run_list = runs.list()
run_logs = {name: runs.logs(name) for name, _ in run_list}
if not run_list:
    st.write("(no runs yet)")
for name, status in run_list:
    with st.expander(f"{name}  •  {status}", expanded=name == st.session_state.get("last_run")):
        st.code(run_logs[name].split(RESULTS_BEGIN, 1)[0][-20000:] or "(no logs yet)")
        if st.button(f"🧹 Remove {name}", key=f"rm-{name}"):
            try:
                runs.remove(name)
                st.rerun()
            except Exception as e:
                st.error(f"Remove error: {e}")

st.markdown("---")
st.subheader("📊 Results")

finished = [(name, status) for name, status in run_list if RESULTS_END in run_logs[name]]
if not finished:
    st.warning("⚠️ No results yet. Run a simulation first.")
else:
    chosen = st.selectbox("Run", [name for name, _ in finished])
    try:
        df = results_from_logs(run_logs[chosen])
        st.dataframe(df)
        st.download_button("Download CSV", df.to_csv(index=False), file_name=f"{chosen}.csv", mime="text/csv")
        numeric_cols = [c for c in df.columns if c != "time" and pd.api.types.is_numeric_dtype(df[c])]
        outputs = [c for c in numeric_cols if c.split("[")[0] in nodes["Outputs"]]
        selected = st.multiselect("Select variables to plot:", numeric_cols, default=outputs[:2])
        if selected:
            st.line_chart(df.set_index("time")[selected])
        else:
            st.info("Select one or more variables to plot.")
    except Exception as e:
        st.error(f"Error reading the results: {e}")
