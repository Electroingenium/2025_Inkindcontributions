# Liqo tutorial: two clusters from scratch

This tutorial sets up two local Kubernetes clusters with [kind](https://kind.sigs.k8s.io), peers them with [Liqo](https://liqo.io), and runs a pod in one cluster from the other. Then it deploys the fmugen demo stack on them (see [docker/Readme.md](../docker/Readme.md)). On Windows, run the commands in Git Bash or WSL, with Docker Desktop running.

## 1. Install the tools

- **Docker Desktop**, running.
- **kind** and **kubectl**:

  ```bash
  winget install Kubernetes.kind Kubernetes.kubectl
  ```

- **liqoctl**: download the v1.x binary for your OS from the [Liqo releases](https://github.com/liqotech/liqo/releases) and put it on your `PATH`. The demo stack was tested with v1.2.0.

Check the tools:

```bash
kind version && kubectl version --client && liqoctl version --client
```

## 2. Create two clusters

Give each cluster its own kubeconfig file, so every command says which cluster it talks to:

```bash
mkdir -p ~/.kube/liqo-demo
kind create cluster --name local --kubeconfig ~/.kube/liqo-demo/local.yaml
kind create cluster --name remote --kubeconfig ~/.kube/liqo-demo/remote.yaml
```

## 3. Install Liqo in both clusters

```bash
liqoctl install kind --kubeconfig ~/.kube/liqo-demo/local.yaml --cluster-id local
liqoctl install kind --kubeconfig ~/.kube/liqo-demo/remote.yaml --cluster-id remote
```

## 4. Peer `local` with `remote`

After peering, `local` can send workloads to `remote`:

```bash
liqoctl peer --kubeconfig ~/.kube/liqo-demo/local.yaml \
  --remote-kubeconfig ~/.kube/liqo-demo/remote.yaml --gw-server-service-type NodePort
```

`remote` now shows up in `local` as a node with the label `liqo.io/type=virtual-node`. It becomes Ready after a minute or a few:

```bash
kubectl --kubeconfig ~/.kube/liqo-demo/local.yaml get nodes
liqoctl info --kubeconfig ~/.kube/liqo-demo/local.yaml
```

## 5. Offload a namespace

Liqo only sends pods from namespaces you offload:

```bash
kubectl --kubeconfig ~/.kube/liqo-demo/local.yaml create namespace demo
liqoctl offload namespace demo --kubeconfig ~/.kube/liqo-demo/local.yaml \
  --namespace-mapping-strategy EnforceSameName --pod-offloading-strategy Remote
```

| Option | Effect |
|---|---|
| `--namespace-mapping-strategy EnforceSameName` | The namespace has the same name in the remote cluster |
| `--pod-offloading-strategy Remote` | Every pod in `demo` runs in the remote cluster |
| `--pod-offloading-strategy LocalAndRemote` | Pods can run in either cluster; each pod's node affinity decides where |

## 6. Run a pod in the remote cluster

```bash
kubectl --kubeconfig ~/.kube/liqo-demo/local.yaml -n demo run hello --image=busybox \
  --restart=Never -- sh -c 'echo hi from $(hostname); sleep 30'
kubectl --kubeconfig ~/.kube/liqo-demo/local.yaml -n demo get pod hello -o wide
```

The `NODE` column shows `remote`. You can read the pod's logs from `local`:

```bash
kubectl --kubeconfig ~/.kube/liqo-demo/local.yaml -n demo logs hello
```

The real pod is in the remote cluster:

```bash
kubectl --kubeconfig ~/.kube/liqo-demo/remote.yaml -n demo get pods
```

If the pod is stuck in `ErrImagePull`, the remote cluster can't pull the image. This happens, for example, when Docker Hub limits your pulls. Load the image into the cluster with `kind load docker-image <image> --name remote`, or push it to a registry both clusters can reach.

Delete the clusters when you're done:

```bash
kind delete cluster --name local
kind delete cluster --name remote
```

## 7. Run the fmugen demo stack

[docker/liqo/up.sh](../docker/liqo/up.sh) does steps 2 to 5 and then deploys the stack:

1. It builds the image and creates the kind clusters `fmu-local` and `fmu-remote`.
2. It loads the image into both clusters and installs Liqo in both.
3. It peers `fmu-local` with `fmu-remote`.
4. It deploys `docker/k8s` and offloads `fmu-sim` with `LocalAndRemote`.

From the repository root:

```bash
bash docker/liqo/up.sh
kubectl --kubeconfig ~/.kube/fmu-sim/local.yaml -n fmu-sim port-forward svc/streamlit-ui 8501
```

Open http://localhost:8501 and start a run. It shows up as `fmu-run-… • succeeded on fmu-remote`:

- The OPC UA server and the UI stay in `fmu-local`, because their node affinity is `liqo.io/type NotIn [virtual-node]`.
- The run Job goes to the virtual node. **Run on** in the sidebar changes that.
- The run reaches `opc.tcp://opcua-server:4840` through the Service that Liqo reflects into `fmu-remote`.
- The UI gets the results from the run's log, read through the virtual node.

To build another model:

```bash
MODEL=examples/simple_pid bash docker/liqo/up.sh
```

To delete both clusters:

```bash
bash docker/liqo/down.sh
```

## Real clusters

The steps are the same, with these changes:

- Install Liqo with `liqoctl install <provider>` (`k3s`, `kubeadm`, `eks`, `aks`, `gke`, …).
- Peering needs the clusters' Liqo gateways to reach each other. Use `--gw-server-service-type LoadBalancer`, or a NodePort that the other cluster can reach.
- Push the image to a registry that every cluster can pull from, and set it in [docker/k8s/kustomization.yaml](../docker/k8s/kustomization.yaml).

Then follow "Your own clusters" in [docker/Readme.md](../docker/Readme.md).
