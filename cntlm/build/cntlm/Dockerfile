FROM alpine:latest
RUN apk update && apk add --no-cache ca-certificates cntlm netcat-openbsd
COPY Bosch-CA-DE.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates