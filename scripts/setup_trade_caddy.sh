#!/bin/bash
set -e

echo "Installing Caddy..."
sudo apt-get update -qq
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -qq
sudo apt-get install -y caddy

echo "Configuring Caddy for trade.goldenpath.kr -> localhost:8080..."
cat << 'EOF' | sudo tee /etc/caddy/Caddyfile
trade.goldenpath.kr {
    reverse_proxy localhost:8080
}
EOF

echo "Restarting Caddy..."
sudo systemctl restart caddy
sudo systemctl enable caddy
echo "Done!"
