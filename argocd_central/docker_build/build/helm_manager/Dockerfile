FROM alpine:latest
COPY apk_list.txt /apk_list.txt
RUN apk update && \
    apk add --no-cache $(tr '\n' ' ' < /apk_list.txt) && \
    rm -rf /var/cache/apk/*
WORKDIR /workspace
COPY setup.sh .
ENV ARGOCD=true
ENTRYPOINT [ "bash", "setup.sh" ]