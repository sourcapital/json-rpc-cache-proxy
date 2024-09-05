FROM openresty/openresty:alpine

RUN apk add --no-cache lua-cjson

COPY nginx.conf.template /usr/local/openresty/nginx/conf/nginx.conf.template
COPY generate-configs.sh /generate-configs.sh
COPY generate-nginx-config.sh /generate-nginx-config.sh

RUN mkdir -p /var/cache/nginx/json_rpc_cache_proxy && \
    chown -R nobody:nobody /var/cache/nginx && \
    chmod -R 755 /var/cache/nginx && \
    chmod +x /generate-configs.sh /generate-nginx-config.sh

EXPOSE 80

CMD ["/bin/sh", "-c", "/generate-nginx-config.sh && /generate-configs.sh"]