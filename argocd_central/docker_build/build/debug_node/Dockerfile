FROM alpine:latest

RUN apk add --no-cache \
    btop \
    neovim \
    htop \
    nano \
    tmux \
    iftop \
    bmon \
    net-tools \
    nmap \
    bind-tools \
    socat \
    netcat-openbsd \
    ncdu \
    fzf \
    openssh \
    sshfs \
    git \
    curl \
    wget \
    zip \
    yq \
    jq \
    bash \
    kubectl \
    helm
COPY setup-neovim.sh /setup-neovim.sh
RUN bash setup-neovim.sh