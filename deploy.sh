#!/bin/bash
# deploy.sh — One-shot setup on Amazon Linux 2 EC2 (Free Tier t2.micro)
# Run as: bash deploy.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

REPO_DIR="/home/ec2-user/regime_bot"
VENV_DIR="$REPO_DIR/venv"
SERVICE_NAME="regime-bot"

echo ""
echo "══════════════════════════════════════════════════"
echo "  Zoya Regime-Adaptive Bot — EC2 Deploy Script"
echo "══════════════════════════════════════════════════"
echo ""

# ── 1. System dependencies ────────────────────────────────────────────────────
echo "→ Installing system dependencies..."
sudo yum update -y -q
sudo yum install -y python3 python3-pip nginx git -q

# ── 2. Create directories ─────────────────────────────────────────────────────
echo "→ Setting up directories..."
mkdir -p "$REPO_DIR/logs"
mkdir -p "$REPO_DIR/frontend/dist"

# ── 3. Python virtualenv ──────────────────────────────────────────────────────
echo "→ Creating Python virtualenv..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Install packages (lightweight — fits t2.micro comfortably)
echo "→ Installing Python packages..."
pip install --upgrade pip -q
pip install \
  ccxt==4.3.95 \
  pandas==2.2.2 \
  numpy==1.26.4 \
  flask==3.0.3 \
  flask-cors==4.0.1 \
  requests==2.32.3 \
  -q

echo "✓ Python packages installed"
pip list | grep -E "ccxt|pandas|numpy|flask"

# ── 4. Copy bot files ─────────────────────────────────────────────────────────
echo "→ Copying bot files..."
cp regime_engine.py     "$REPO_DIR/"
cp binance_executor.py  "$REPO_DIR/"
cp dashboard_api.py     "$REPO_DIR/"

# ── 5. Environment file ───────────────────────────────────────────────────────
if [ ! -f "$REPO_DIR/.env" ]; then
  cp .env.template "$REPO_DIR/.env"
  echo ""
  echo "⚠  .env file created — EDIT IT BEFORE STARTING:"
  echo "   nano $REPO_DIR/.env"
  echo ""
fi

# ── 6. Systemd service ────────────────────────────────────────────────────────
echo "→ Installing systemd service..."
sudo cp regime-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME

# ── 7. Nginx config ───────────────────────────────────────────────────────────
echo "→ Configuring Nginx..."
sudo cp nginx.conf /etc/nginx/conf.d/crypto.aspiretekstudio.com.conf

# Test nginx config
sudo nginx -t && echo "✓ Nginx config valid"
sudo systemctl enable nginx
sudo systemctl start nginx || sudo systemctl reload nginx

# ── 8. SSL via Certbot ────────────────────────────────────────────────────────
if ! command -v certbot &> /dev/null; then
  echo "→ Installing certbot..."
  sudo pip install certbot certbot-nginx -q
fi
echo ""
echo "→ To enable HTTPS run:"
echo "   sudo certbot --nginx -d crypto.aspiretekstudio.com"
echo ""

# ── 9. Firewall ───────────────────────────────────────────────────────────────
echo "→ Opening ports 80 and 443 (ensure Security Group allows these in AWS)..."
sudo iptables -I INPUT -p tcp --dport 80  -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true

# ── 10. Summary ───────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ Deploy complete!"
echo "══════════════════════════════════════════════════"
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. Edit your credentials:"
echo "     nano $REPO_DIR/.env"
echo ""
echo "  2. Start in PAPER mode first (PAPER=true in .env)"
echo "     sudo systemctl start $SERVICE_NAME"
echo ""
echo "  3. Watch logs:"
echo "     sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "  4. Enable SSL:"
echo "     sudo certbot --nginx -d crypto.aspiretekstudio.com"
echo ""
echo "  5. When comfortable → set PAPER=false in .env and restart:"
echo "     sudo systemctl restart $SERVICE_NAME"
echo ""
echo "  Dashboard: https://crypto.aspiretekstudio.com"
echo "  API:       https://crypto.aspiretekstudio.com/api/status"
echo ""
echo "  Memory usage check (should be <300MB on t2.micro):"
echo "     free -h"
echo "     ps aux | grep python"
echo ""
