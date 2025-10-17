#!/bin/bash


install_kubeopsview() {
  local NAMESPACE="kube-system"
  local RELEASE="kube-ops-view"

  if [ "$1" == "true" ]; then
    until (
      set -e

      if helm list -n "$NAMESPACE" | grep -qE "^\s*$RELEASE\s"; then
        echo "✅ $RELEASE already exists in namespace $NAMESPACE. Skipping installation."
        return 0
      fi
      echo "🚀 Installing $RELEASE in namespace $NAMESPACE..."
      helm repo add christianhuth https://charts.christianhuth.de --force-update
      helm repo update
      helm upgrade --install "$RELEASE" christianhuth/kube-ops-view \
        --namespace "$NAMESPACE" --create-namespace \
        --set service.type=NodePort \
        --set service.port=8080

      kubectl patch svc "$RELEASE" -n "$NAMESPACE" \
        --type=merge \
        -p '{"spec": {"ports": [{"name": "http", "port": 8080, "protocol": "TCP", "targetPort": "http", "nodePort": 30002}]}}'

      kubectl set env deployment "$RELEASE" -n "$NAMESPACE" QUERY_INTERVAL=10

      kubectl patch deployment "$RELEASE" -n "$NAMESPACE" \
        --type='merge' \
        -p '{
          "spec": {
            "template": {
              "spec": {
                "tolerations": [
                  {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists"
                  },
                  {
                    "key": "node-role.kubernetes.io/master",
                    "operator": "Exists"
                  },
                  {
                    "key": "CriticalAddonsOnly",
                    "operator": "Exists"
                  }
                ]
              }
            }
          }
        }'
    ); do
      echo "❌ install failed. Retrying in 10s..."
      sleep 10
    done
  else
    if ! helm status "$RELEASE" -n "$NAMESPACE" > /dev/null 2>&1; then
      echo "✅ $RELEASE not found in namespace $NAMESPACE. Skipping removal."
      return 0
    fi
    echo "🗑️ Uninstalling $RELEASE from namespace $NAMESPACE..."
    helm uninstall "$RELEASE" -n "$NAMESPACE" || true
  fi
}

install_kubeopsview $KUBEOPSVIEW

install_argocd() {
  local NAMESPACE="argocd"
  local RELEASE="argocd"

  if [ "$1" == "true" ]; then
    until (
      set -e

      if helm list -n "$NAMESPACE" | grep -qE "^\s*$RELEASE\s"; then
        echo "✅ $RELEASE already exists in namespace $NAMESPACE. Skipping installation."
        exit 0
      fi

      echo "🚀 Installing $RELEASE in namespace $NAMESPACE..."
      helm repo add argo https://argoproj.github.io/argo-helm --force-update
      helm repo update

      kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
      helm install "$RELEASE" argo/argo-cd \
        --namespace "$NAMESPACE" \
        --wait \
        --set server.service.type=NodePort \
        --set server.service.nodePortHttps=30001

      kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -
      kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
      kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/dashboard-install.yaml

      kubectl patch configmap argocd-cm -n "$NAMESPACE" --type merge -p '{
        "data": {
          "resource.customizations": "argoproj.io/Rollout:\n  ignoreDifferences: |\n    jsonPointers:\n      - /spec/replicas\n",
          "resource.customizations.health.argoproj.io_Rollout": "hs = {}\nif obj.status ~= nil then\n  if obj.status.health ~= nil then\n    hs.status = obj.status.health.status\n    hs.message = obj.status.health.message\n    return hs\n  end\nend\nhs.status = \"Progressing\"\nhs.message = \"Waiting for rollout\"\nreturn hs"
        }
      }'

      kubectl rollout restart deployment argocd-repo-server -n "$NAMESPACE"
      kubectl apply -n "$NAMESPACE" -f https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/manifests/install.yaml
    ); do
      echo "❌ install failed. Retrying in 10s..."
      sleep 10
    done

  else
    if ! helm status "$RELEASE" -n "$NAMESPACE" > /dev/null 2>&1; then
      echo "✅ $RELEASE not found in namespace $NAMESPACE. Skipping removal."
      return 0
    fi
    echo "🗑️ Uninstalling $RELEASE from namespace $NAMESPACE..."
    helm uninstall "$RELEASE" -n "$NAMESPACE" || true
    kubectl delete namespace "$NAMESPACE" --ignore-not-found
    kubectl delete namespace argo-rollouts --ignore-not-found
  fi
}

install_argocd $ARGOCD
