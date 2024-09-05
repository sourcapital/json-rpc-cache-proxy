#!/bin/sh

# Get the Docker network subnet
DOCKER_IP=$(ip route | grep default | awk '{print $3}')
DOCKER_SUBNET=$(echo $DOCKER_IP | cut -d. -f1-2).0.0/16

# Generate the Nginx configuration file
sed "s|DOCKER_SUBNET|$DOCKER_SUBNET|g" /usr/local/openresty/nginx/conf/nginx.conf.template > /usr/local/openresty/nginx/conf/nginx.conf

echo "Generated Nginx config with Docker subnet: $DOCKER_SUBNET"