#!/bin/bash

build_and_push_k8s_images() {
  set -euo pipefail

  local INTERNAL_REGISTRY="localhost"
  local INTERNAL_REGISTRY_TO_SKIP="registry.internal.local"

  log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
  success() { echo -e "\033[1;32m[SUCCESS]\033[0m $*"; }
  warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
  error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; }

  log "Extracting images from Kubernetes cluster..."
  local IMAGES
  IMAGES=$(kubectl get pods --all-namespaces -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.image}{"\n"}{end}{range .spec.initContainers[*]}{.image}{"\n"}{end}{range .spec.ephemeralContainers[*]}{.image}{"\n"}{end}' \
    | sed -E 's/@sha256:[a-f0-9]+//' \
    | grep -v '^sha256:' \
    | grep -v "^${INTERNAL_REGISTRY_TO_SKIP}/" \
    | sort -u)

  if [[ -z "$IMAGES" ]]; then
    warn "No external images found. Exiting."
    return 0
  fi

  log "Initializing docker-compose.yml..."
  echo "services:" > docker-compose.yml

  for IMAGE in $IMAGES; do
    local IMAGE_WITHOUT_REGISTRY
    IMAGE_WITHOUT_REGISTRY=$(echo "$IMAGE" | sed -E 's~^[^/]+/~~')

    local IMAGE_TAG
    IMAGE_TAG=$(echo "$IMAGE" | awk -F':' '{print $NF}')
    [[ "$IMAGE_TAG" == "$IMAGE_WITHOUT_REGISTRY" ]] && IMAGE_TAG="latest"

    local SERVICE_NAME
    SERVICE_NAME=$(echo "${IMAGE_WITHOUT_REGISTRY}" | sed -E 's/[^a-zA-Z0-9_-]+/-/g')

    local TARGET_IMAGE="${INTERNAL_REGISTRY}:5000/${IMAGE_WITHOUT_REGISTRY}"

    mkdir -p "build/${SERVICE_NAME}"
    echo "FROM ${IMAGE}" > "build/${SERVICE_NAME}/Dockerfile"

    cat >> docker-compose.yml <<EOL
  ${SERVICE_NAME}:
    image: ${TARGET_IMAGE}
    build:
      context: build/${SERVICE_NAME}
EOL

    success "Added service: ${SERVICE_NAME} -> ${TARGET_IMAGE}"
  done

  export DOCKER_BUILDKIT=1
  export COMPOSE_DOCKER_CLI_BUILD=1
  export BUILDKIT_STEP_LOG_MAX_SIZE=104857600
  export BUILDKIT_STEP_LOG_MAX_SPEED=4194304

  local SUCCESS_LOG="build_success.log"
  local FAILED_LOG="build_failed.log"
  > "$SUCCESS_LOG"
  > "$FAILED_LOG"

  log "Starting build process..."
  local SERVICES
  SERVICES=$(yq '.services | keys | .[]' docker-compose.yml | tr -d '"')

  for SERVICE in $SERVICES; do
    log "Building service: $SERVICE ..."
    if docker compose build "$SERVICE"; then
      echo "$SERVICE" >> "$SUCCESS_LOG"
      success "Build succeeded: $SERVICE"
      docker compose push "$SERVICE"
    else
      echo "$SERVICE" >> "$FAILED_LOG"
      error "Build failed: $SERVICE"
    fi
    docker system prune -a -f
  done
}

# Call the function
build_and_push_k8s_images
