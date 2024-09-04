FROM openresty/openresty:alpine

RUN apk add --no-cache lua-cjson

COPY nginx.conf /usr/local/openresty/nginx/conf/nginx.conf
COPY generate-configs.sh /generate-configs.sh

RUN mkdir -p /var/cache/nginx/json_rpc_cache_proxy && \
    chown -R nobody:nobody /var/cache/nginx && \
    chmod -R 755 /var/cache/nginx && \
    chmod +x /generate-configs.sh

EXPOSE 80

CMD ["/bin/sh", "/generate-configs.sh"]