#!/bin/bash
sudo mv /tmp/.env /opt/bitget/current/.env
sudo mkdir -p /opt/bitget/current/scripts
sudo mv /tmp/run_live_bot.py /opt/bitget/current/scripts/run_live_bot.py
sudo mv /tmp/dashboard.py /opt/bitget/current/scripts/dashboard.py
sudo mv /tmp/aggressive_live.toml /opt/bitget/current/config/aggressive_live.toml
sudo chown -R bitget:bitget /opt/bitget/current/.env /opt/bitget/current/scripts /opt/bitget/current/config/aggressive_live.toml
sudo chmod 600 /opt/bitget/current/.env

# Update bitget-bot.service
sudo sed -i 's|ExecStart=.*|ExecStart=/usr/bin/python3 /opt/bitget/current/scripts/run_live_bot.py|' /usr/lib/systemd/system/bitget-bot.service

# Update bitget-dashboard.service
sudo sed -i 's|ExecStart=.*|ExecStart=/usr/bin/python3 /opt/bitget/current/scripts/dashboard.py|' /usr/lib/systemd/system/bitget-dashboard.service

# Caddy port update
echo ':80 {
    reverse_proxy localhost:8080
}' | sudo tee /etc/caddy/Caddyfile

sudo systemctl daemon-reload
sudo systemctl restart bitget-bot bitget-dashboard caddy
