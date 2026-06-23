#!/usr/bin/env bash
# =============================================================================
# One-time server bootstrap for a fresh Ubuntu 24.04 LTS VPS (Hetzner / DO).
#
# Installs Docker + Compose, a small swap file, a firewall (SSH/HTTP/HTTPS only),
# fail2ban, and automatic security updates. Safe to re-run (idempotent-ish).
#
# Run as root on the new server:
#   bash server-setup.sh
# =============================================================================
set -euo pipefail

echo "==> Updating base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y ca-certificates curl gnupg git ufw fail2ban unattended-upgrades

# --- Docker engine + compose plugin (official repo) --------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
else
  echo "==> Docker already installed — skipping"
fi

# --- Swap (helps the 4 GB box during image builds) ---------------------------
if [ ! -f /swapfile ]; then
  echo "==> Creating 2 GB swap file"
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
  echo "==> Swap file already present — skipping"
fi

# --- Firewall: only SSH + HTTP + HTTPS ---------------------------------------
echo "==> Configuring UFW firewall"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose

# --- fail2ban + auto security updates ----------------------------------------
echo "==> Enabling fail2ban + unattended-upgrades"
systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades || true

echo
echo "============================================================"
echo " Server is ready."
echo " Next:"
echo "   1. git clone <your GitHub repo>  &&  cd <repo>/deploy"
echo "   2. cp env.example .env  &&  edit .env  (secrets + DOMAIN)"
echo "   3. bash deploy.sh"
echo
echo " This server's public IPv4 (whitelist it on the marketplaces):"
curl -fsS --max-time 8 https://api.ipify.org || echo "  (could not auto-detect — check the provider dashboard)"
echo
echo "============================================================"
