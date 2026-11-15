#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHARE_DIR="$HOME/.local/share/kde-bing-potd-refresh"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$SHARE_DIR" "$BIN_DIR" "$SYSTEMD_DIR"

rm -rf "$SHARE_DIR/kde_bing_potd_refresh"
cp -r "$REPO_DIR/src/kde_bing_potd_refresh" "$SHARE_DIR/kde_bing_potd_refresh"

cat > "$BIN_DIR/kde-bing-potd-refresh" <<'EOF'
#!/usr/bin/env bash
PYTHONPATH="$HOME/.local/share/kde-bing-potd-refresh${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m kde_bing_potd_refresh "$@"
EOF
chmod 755 "$BIN_DIR/kde-bing-potd-refresh"

cp -f "$REPO_DIR/systemd/kde-bing-potd-refresh.service" "$SYSTEMD_DIR/kde-bing-potd-refresh.service"
cp -f "$REPO_DIR/systemd/kde-bing-potd-refresh.timer" "$SYSTEMD_DIR/kde-bing-potd-refresh.timer"

systemctl --user daemon-reload
systemctl --user enable --now kde-bing-potd-refresh.timer

echo "[OK] Installed kde-bing-potd-refresh to $SHARE_DIR and $BIN_DIR/kde-bing-potd-refresh"
echo "[OK] Enabled systemd --user timer kde-bing-potd-refresh.timer"
