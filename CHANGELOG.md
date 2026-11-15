# Changelog

All notable changes to **KDE Bing Wallpaper Timezone Sync** (`kde-bing-potd-refresh`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.1.0](https://github.com/russellmilliner/kde-bing-potd-refresh/releases/tag/v0.1.0) — 2026-11-15

### Added
- Packaged Python CLI (`kde_bing_potd_refresh`) with `pyproject.toml` console script entrypoint and zero external runtime dependencies.
- CLI flags: `--status` / `--check`, `--force`, `--json`, `--market` (`BING_POTD_MARKET`), `--cache-dir`, `--install-timer`, `--uninstall-timer`, and `--version`.
- Bundled `systemd --user` service (`kde-bing-potd-refresh.service`) and Pacific-anchored timer (`kde-bing-potd-refresh.timer` firing at `00:05` & `00:35 America/Los_Angeles` plus `OnStartupSec=45s` with `Persistent=true`).
- Arch Linux / EndeavourOS `PKGBUILD` (`packaging/arch/PKGBUILD`), portable user installer/uninstaller (`scripts/install.sh`, `scripts/uninstall.sh`), and multi-artifact package builder (`scripts/build-packages.sh`).
- Unit test suite (`tests/test_cli.py`) and GitHub Actions CI workflow (`.github/workflows/ci.yml`).
- Full repository documentation (`README.md`, `docs/ARCHITECTURE.md`, `docs/TROUBLESHOOTING.md`).
