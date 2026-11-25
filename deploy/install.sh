#!/usr/bin/env bash
# Telepítő Debian/Ubuntu alapú szerverre (VPS, Raspberry Pi OS is jó).
# Futtatás rootként a projekt mappájából:
#     sudo ./deploy/install.sh                  # HTTP, a szerver IP-címén
#     sudo ./deploy/install.sh adat.pelda.hu    # HTTPS, saját tartománnyal (az A rekord a szerverre mutasson)
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Rootként futtasd (sudo)." >&2; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${1:-}"
APP=/opt/hu-aramlas
WEB=/var/www/hu-aramlas
ENVF=/etc/hu-aramlas.env

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv caddy

id aramlas >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin aramlas

mkdir -p "$APP" "$WEB"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q -r "$SRC/requirements.txt"
install -m 0644 "$SRC/collector.py" "$APP/collector.py"
install -m 0644 "$SRC"/*.html "$SRC"/demo-*.json "$SRC"/europe-geo.json "$SRC"/hu-geo.json "$WEB/"
install -d "$WEB/assets"
install -m 0644 "$SRC"/assets/* "$WEB/assets/"
chown -R aramlas:aramlas "$WEB"

# Token: a környezetből vagy kérdezve (nem látszik a képernyőn, nem kerül parancssorba).
if [ ! -s "$ENVF" ]; then
  TOKEN="${ENTSOE_TOKEN:-}"
  if [ -z "$TOKEN" ]; then read -r -s -p "ENTSO-E token: " TOKEN; echo; fi
  [ -n "$TOKEN" ] || { echo "Token nélkül nem megy." >&2; exit 1; }
  umask 077
  printf 'ENTSOE_TOKEN=%s\n' "$TOKEN" > "$ENVF"
  chown root:root "$ENVF"; chmod 600 "$ENVF"
fi

install -m 0644 "$SRC/deploy/hu-aramlas.service" /etc/systemd/system/hu-aramlas.service
install -m 0644 "$SRC/deploy/hu-aramlas.timer" /etc/systemd/system/hu-aramlas.timer

if [ -n "$DOMAIN" ]; then SITE="$DOMAIN"; else SITE=":80"; fi
sed "s|__SITE__|$SITE|" "$SRC/deploy/Caddyfile" > /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl enable --now hu-aramlas.timer
systemctl restart caddy

echo "Első adatgyűjtés..."
if systemctl start hu-aramlas.service; then
  echo "Kész: $( [ -n "$DOMAIN" ] && echo "https://$DOMAIN/" || echo "http://<a-szerver-IP-címe>/" )"
else
  echo "Az első futás hibázott. Napló: journalctl -u hu-aramlas.service -n 50" >&2
  exit 1
fi
