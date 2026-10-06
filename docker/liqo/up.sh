#!/usr/bin/env bash
# A local Liqo playground: two kind clusters, peered with Liqo, running the stack.
#
#   fmu-local   runs the OPC UA server and the UI; its namespace fmu-sim is offloaded
#   fmu-remote  appears in fmu-local as a virtual node; FMU runs are scheduled there
#
# Needs docker, kind, kubectl and liqoctl (https://github.com/liqotech/liqo/releases, v1.x).
# Run from anywhere: bash docker/liqo/up.sh. Then:
#   kubectl --kubeconfig ~/.kube/fmu-sim/local.yaml -n fmu-sim port-forward svc/streamlit-ui 8501
# and open http://localhost:8501. Tear down with docker/liqo/down.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KUBE_DIR="${KUBE_DIR:-$HOME/.kube/fmu-sim}"
IMAGE="${IMAGE:-fmugen-sim:latest}"
MODEL="${MODEL:-examples/psychrometry}"
LOCAL=fmu-local
REMOTE=fmu-remote
mkdir -p "$KUBE_DIR"

echo "==> Building $IMAGE ($MODEL)"
docker build -f "$REPO/docker/Dockerfile" --build-arg "MODEL=$MODEL" -t "$IMAGE" "$REPO"

for cluster in "$LOCAL" "$REMOTE"; do
  kubeconfig="$KUBE_DIR/${cluster#fmu-}.yaml"
  if ! kind get clusters | grep -qx "$cluster"; then
    echo "==> Creating kind cluster $cluster"
    kind create cluster --name "$cluster" --kubeconfig "$kubeconfig" --wait 120s
  fi
  echo "==> Loading $IMAGE into $cluster"
  kind load docker-image "$IMAGE" --name "$cluster"
  if ! kubectl --kubeconfig "$kubeconfig" get ns liqo >/dev/null 2>&1; then
    echo "==> Installing Liqo in $cluster"
    liqoctl install kind --kubeconfig "$kubeconfig" --cluster-id "$cluster"
  fi
done

L="$KUBE_DIR/local.yaml"
R="$KUBE_DIR/remote.yaml"

if ! kubectl --kubeconfig "$L" get foreignclusters "$REMOTE" >/dev/null 2>&1; then
  echo "==> Peering $LOCAL -> $REMOTE"
  liqoctl peer --kubeconfig "$L" --remote-kubeconfig "$R" --gw-server-service-type NodePort
fi
echo "==> Waiting for the virtual node $REMOTE"
until kubectl --kubeconfig "$L" get node "$REMOTE" >/dev/null 2>&1; do sleep 2; done
kubectl --kubeconfig "$L" wait --for=condition=Ready "node/$REMOTE" --timeout 180s

echo "==> Deploying the stack in $LOCAL"
# Apply the manifests with $IMAGE in place of the image kustomization.yaml names
kubectl kustomize "$REPO/docker/k8s" | sed "s#image: fmugen-sim:latest#image: $IMAGE#" \
  | kubectl --kubeconfig "$L" apply -f -

echo "==> Offloading namespace fmu-sim"
liqoctl offload namespace fmu-sim --kubeconfig "$L" \
  --namespace-mapping-strategy EnforceSameName --pod-offloading-strategy LocalAndRemote

# Pick up a rebuilt image that kept its tag
kubectl --kubeconfig "$L" -n fmu-sim rollout restart deploy/opcua-server deploy/streamlit-ui
kubectl --kubeconfig "$L" -n fmu-sim rollout status deploy/opcua-server deploy/streamlit-ui --timeout 180s
kubectl --kubeconfig "$L" get nodes

cat <<EOF

Ready. Open the UI with:
  kubectl --kubeconfig "$L" -n fmu-sim port-forward svc/streamlit-ui 8501
  http://localhost:8501
Runs go to the virtual node ($REMOTE) by default; "Run on" in the sidebar changes that.
EOF
