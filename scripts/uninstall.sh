#!/usr/bin/env bash
set -euo pipefail

SHARE_DIR="$HOME/.local/share/kde-bing-potd-refresh"
BIN_PATH="$HOME/.local/bin/kde-bing-potd-refresh"
SYSTEMD_DIR="$HOME/.config/systemd/user"

systemctl --user disable --now kde-bing-potd-refresh.timer >/dev/null 2>&1 || true
rm -f "$SYSTEMD_DIR/kde-bing-potd-refresh.service" "$SYSTEMD_DIR/kde-bing-potd-refresh.timer"
systemctl --user daemon-reload >/dev/null 2>&1 || true

rm -f "$BIN_PATH"
rm -rf "$SHARE_DIR"

echo "[OK] Uninstalled kde-bing-potd-refresh and removed user systemd timer."
