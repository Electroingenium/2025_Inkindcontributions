#!/usr/bin/env bash
# Delete the two kind clusters made by up.sh.
set -euo pipefail
KUBE_DIR="${KUBE_DIR:-$HOME/.kube/fmu-sim}"
kind delete cluster --name fmu-local --kubeconfig "$KUBE_DIR/local.yaml"
kind delete cluster --name fmu-remote --kubeconfig "$KUBE_DIR/remote.yaml"
