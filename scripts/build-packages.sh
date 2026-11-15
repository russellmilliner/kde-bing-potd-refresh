#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_DIR/dist"
VERSION="$(grep -E '^version\s*=' "$REPO_DIR/pyproject.toml" | head -n 1 | sed -E 's/.*"([^"]+)".*/\1/')"
TAG="v${VERSION}"

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "==> Building Python wheel and source distribution..."
(
  cd "$REPO_DIR"
  python3 -m build --outdir "$DIST_DIR"
)

echo "==> Building Arch Linux pacman package (.pkg.tar.zst)..."
ARCH_TMP="$(mktemp -d)"
trap 'rm -rf "$ARCH_TMP"' EXIT
cp "$REPO_DIR/packaging/arch/PKGBUILD" "$ARCH_TMP/"
cp "$DIST_DIR/kde_bing_potd_refresh-${VERSION}.tar.gz" "$ARCH_TMP/"
(
  cd "$ARCH_TMP"
  makepkg -f --noconfirm
)
cp "$ARCH_TMP"/*.pkg.tar.zst "$DIST_DIR/"

echo "==> Building portable Linux tarball..."
STAGE_NAME="kde-bing-potd-refresh-${TAG}-linux-any"
mkdir -p "$DIST_DIR/$STAGE_NAME"
cp -r "$REPO_DIR/src" "$REPO_DIR/systemd" "$REPO_DIR/scripts" \
      "$REPO_DIR/packaging" "$REPO_DIR/docs" \
      "$REPO_DIR/README.md" "$REPO_DIR/CHANGELOG.md" \
      "$REPO_DIR/LICENSE" "$REPO_DIR/MANIFEST.in" "$REPO_DIR/pyproject.toml" \
      "$DIST_DIR/$STAGE_NAME/"
(
  cd "$DIST_DIR"
  tar -czf "${STAGE_NAME}.tar.gz" "$STAGE_NAME"
  rm -rf "$STAGE_NAME"
)

echo "==> Generating SHA-256 checksums..."
(
  cd "$DIST_DIR"
  for f in *.whl *.tar.gz *.pkg.tar.zst; do
    [[ -f "$f" ]] && sha256sum "$f" > "${f}.sha256"
  done
)

echo "[OK] Built all packages in $DIST_DIR:"
ls -lh "$DIST_DIR"
