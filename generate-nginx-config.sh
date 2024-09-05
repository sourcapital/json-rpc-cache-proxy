#!/bin/sh

# Get the Docker network subnet
DOCKER_SUBNET=$(ip route | grep default | awk '{print $3}' | cut -d. -f1-3)".0/24"

# Generate the Nginx configuration file
sed "s|DOCKER_SUBNET|$DOCKER_SUBNET|g" /usr/local/openresty/nginx/conf/nginx.conf.template > /usr/local/openresty/nginx/conf/nginx.conf

echo "Generated Nginx config with Docker subnet: $DOCKER_SUBNET"