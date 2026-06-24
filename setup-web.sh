#!/usr/bin/env bash
# Run this on the GCP VM after git pull to deploy the web dashboard.
# Usage: bash setup-web.sh
set -e
cd /home/emmanuel_maina/wyzant-poller

echo "=== Installing flask ==="
.venv/bin/pip install flask -q
echo "flask installed"

echo ""
echo "=== Updating .env ==="
mkdir -p .state
if ! grep -q "^WEB_USER" .env; then
    printf '\n# Web dashboard\nWEB_USER=admin\nWEB_PASSWORD=makini2024\nWEB_PORT=8080\n' >> .env
    echo "Added WEB_USER / WEB_PASSWORD / WEB_PORT to .env"
else
    echo ".env already has WEB_USER — skipping"
fi
if ! grep -q "^STATE_DIR" .env; then
    printf 'STATE_DIR=/home/emmanuel_maina/wyzant-poller/.state\n' >> .env
    echo "Added STATE_DIR to .env"
fi

echo ""
echo "=== Creating sudoers entry (web restart button) ==="
echo 'emmanuel_maina ALL=(ALL) NOPASSWD: /bin/systemctl start wyzant-poller, /bin/systemctl stop wyzant-poller, /bin/systemctl restart wyzant-poller' \
  | sudo tee /etc/sudoers.d/wyzant-web > /dev/null
sudo chmod 440 /etc/sudoers.d/wyzant-web
echo "sudoers entry written to /etc/sudoers.d/wyzant-web"

echo ""
echo "=== Updating poller service (adds log file output) ==="
sudo tee /etc/systemd/system/wyzant-poller.service > /dev/null << 'EOF'
[Unit]
Description=Wyzant Job Poller
After=network-online.target
Wants=network-online.target

[Service]
User=emmanuel_maina
WorkingDirectory=/home/emmanuel_maina/wyzant-poller
ExecStart=/home/emmanuel_maina/wyzant-poller/.venv/bin/python -m wyzant_poller
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:/home/emmanuel_maina/wyzant-poller/.state/poller.log
StandardError=append:/home/emmanuel_maina/wyzant-poller/.state/poller.log

[Install]
WantedBy=multi-user.target
EOF
echo "poller service updated"

echo ""
echo "=== Creating web dashboard service ==="
sudo tee /etc/systemd/system/wyzant-poller-web.service > /dev/null << 'EOF'
[Unit]
Description=Wyzant Job Radar Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=emmanuel_maina
WorkingDirectory=/home/emmanuel_maina/wyzant-poller
ExecStart=/home/emmanuel_maina/wyzant-poller/.venv/bin/python -m wyzant_poller.web
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
echo "web service created"

echo ""
echo "=== Reloading systemd and starting services ==="
sudo systemctl daemon-reload
sudo systemctl restart wyzant-poller
sudo systemctl enable wyzant-poller-web
sudo systemctl start wyzant-poller-web

sleep 2
echo ""
echo "--- wyzant-poller ---"
sudo systemctl status wyzant-poller --no-pager -l
echo ""
echo "--- wyzant-poller-web ---"
sudo systemctl status wyzant-poller-web --no-pager -l
echo ""

EXT_IP=$(curl -sf --max-time 3 ifconfig.me || echo "<VM-IP>")
echo "=============================================="
echo "  Dashboard: http://${EXT_IP}:8080"
echo "  Login:     admin / makini2024"
echo "=============================================="
echo "Reminder: open GCP firewall for TCP port 8080 if you haven't already."
