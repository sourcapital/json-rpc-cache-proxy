#!/bin/sh

set -e

mkdir -p /usr/local/openresty/nginx/conf/conf.d/upstreams
mkdir -p /usr/local/openresty/nginx/conf/conf.d/locations

DEFAULT_CACHE_TIME=${DEFAULT_CACHE_TIME:-10}

create_configs() {
    name=$1
    url=$2
    cache_time=$3

    protocol=$(echo $url | grep :// | sed -e's,^\(.*://\).*,\1,g')
    url_without_protocol=$(echo ${url#$protocol})
    hostname=$(echo $url_without_protocol | cut -d/ -f1)
    path=$(echo $url_without_protocol | cut -d/ -f2-)

    # Resolve hostname to IPv4 address
    ip=$(getent ahostsv4 "$hostname" | head -n1 | awk '{print $1}')
    if [ -z "$ip" ]; then
        echo "Failed to resolve IPv4 address for $hostname"
        return 1
    fi

    cat << EOF > /usr/local/openresty/nginx/conf/conf.d/upstreams/${name}.conf
upstream ${name} {
    server ${ip}:443;
    keepalive 64;
}
EOF

    cat << EOF > /usr/local/openresty/nginx/conf/conf.d/locations/${name}.conf
location /${name} {
    rewrite ^/${name}(.*) /${path}\$1 break;

    set \$modified_body '';

    access_by_lua_block {
        ngx.req.read_body()
        local body = ngx.req.get_body_data()
        if body then
            body = body:gsub("%s+", "")
            ngx.var.modified_body = body
            local success, json = pcall(cjson.decode, body)
            if success then
                ngx.ctx.original_id = json.id
                json.id = nil
                local cache_key = cjson.encode(json)
                ngx.var.cache_key = ngx.md5("${name}" .. cache_key)
            else
                ngx.var.cache_key = ngx.md5("${name}" .. body)
            end
        else
            ngx.var.cache_key = ngx.md5("${name}" .. ngx.var.request_uri)
        end
    }

    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \$connection_upgrade;
    proxy_set_header Host ${hostname};
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;

    proxy_ssl_server_name on;
    proxy_ssl_name ${hostname};
    proxy_ssl_verify off;

    proxy_cache json_rpc_cache;
    proxy_cache_key \$request_method||\$cache_key;
    proxy_cache_valid 200 ${cache_time}s;
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    proxy_cache_lock on;
    proxy_cache_lock_timeout 5s;
    proxy_cache_methods POST;

    proxy_pass https://${name};

    header_filter_by_lua_block {
        if ngx.var.http_upgrade ~= "websocket" then
            ngx.header.content_length = nil
        end
    }

    body_filter_by_lua_block {
        if ngx.var.http_upgrade ~= "websocket" then
            local chunk = ngx.arg[1]
            local eof = ngx.arg[2]

            if not ngx.ctx.buffer then
                ngx.ctx.buffer = ""
            end

            if chunk then
                ngx.ctx.buffer = ngx.ctx.buffer .. chunk
            end

            if eof then
                local success, response = pcall(cjson.decode, ngx.ctx.buffer)
                if success and ngx.ctx.original_id then
                    response.id = ngx.ctx.original_id
                    ngx.arg[1] = cjson.encode(response)
                else
                    ngx.arg[1] = ngx.ctx.buffer
                end
                ngx.arg[2] = true
            else
                ngx.arg[1] = nil
            end
        end
    }

    add_header X-Cache-Status \$upstream_cache_status;
    add_header X-Cache-Key \$cache_key;
}
EOF
}

env | while IFS='=' read -r key value; do
    case "$key" in
        RPC_NODE_*)
            name=$(echo "$key" | cut -d'_' -f3- | tr '[:upper:]' '[:lower:]')
            cache_time_var="CACHE_TIME_$(echo "$name" | tr '[:lower:]' '[:upper:]')"
            cache_time=$(eval echo \$${cache_time_var:-$DEFAULT_CACHE_TIME})
            
            if echo "$value" | grep -q "^https\?://"; then
                create_configs "$name" "$value" "$cache_time"
            fi
            ;;
    esac
done

/usr/local/openresty/bin/openresty -g 'daemon off;'