FROM registry:2
COPY registry_config.yml /etc/docker/registry/config.yml
HEALTHCHECK --interval=10s --timeout=5s --retries=5 CMD nc -z localhost 5000 || exit 1