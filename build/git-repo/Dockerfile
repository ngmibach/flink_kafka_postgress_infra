FROM nginx:stable-alpine

RUN apk add --no-cache git-daemon fcgiwrap spawn-fcgi apache2-utils

COPY nginx.conf /etc/nginx/nginx.conf.template

COPY repo_init.sh /repo_init.sh

RUN touch /log.txt && chmod 777 /repo_init.sh /log.txt

VOLUME ["/git"]

EXPOSE 3000

CMD spawn-fcgi -s /run/fcgi.sock /usr/bin/fcgiwrap && \
    envsubst '\${SERVER_NAME}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf && \
    nginx -g "daemon off;"