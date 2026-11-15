"""CLI and systemd timer manager for KDE Plasma 6 Bing Picture of the Day sync."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.resources
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Sequence
import urllib.error
import urllib.parse
import urllib.request

from kde_bing_potd_refresh import __version__

DEFAULT_BING_API_URL = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1"
SERVICE_NAME = "kde-bing-potd-refresh.service"
TIMER_NAME = "kde-bing-potd-refresh.timer"

JS_CLEAR_BING = """
for (const d of desktops()) {
    if (d.wallpaperPlugin === "org.kde.potd") {
        d.currentConfigGroup = ["Wallpaper", "org.kde.potd", "General"];
        if (d.readConfig("Provider") === "bing") {
            d.writeConfig("Provider", "");
        }
    }
}
"""

JS_RESTORE_BING = """
for (const d of desktops()) {
    if (d.wallpaperPlugin === "org.kde.potd") {
        d.currentConfigGroup = ["Wallpaper", "org.kde.potd", "General"];
        if (d.readConfig("Provider") === "") {
            d.writeConfig("Provider", "bing");
        }
    }
}
"""


def get_default_cache_dir() -> Path:
    """Return the default KDE Plasma POTD cache directory."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return base / "plasma_engine_potd"


def get_default_systemd_user_dir() -> Path:
    """Return the default systemd user unit directory."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "systemd" / "user"


def find_qdbus_bin() -> str | None:
    """Locate a Qt6/Plasma-compatible qdbus executable on PATH."""
    for candidate in ("qdbus6", "qdbus-qt6", "qdbus"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def build_bing_api_url(market: str | None = None) -> str:
    """Build the Bing HPImageArchive API URL with optional market parameter."""
    mkt = (market or "").strip()
    if not mkt:
        return DEFAULT_BING_API_URL
    return f"{DEFAULT_BING_API_URL}&mkt={urllib.parse.quote(mkt, safe='')}"


def fetch_latest_bing_meta(
    market: str | None = None,
    retries: int = 6,
    delay_sec: float = 5.0,
) -> dict[str, Any] | None:
    """Fetch the latest Bing Picture of the Day JSON metadata with retry backoff."""
    url = build_bing_api_url(market)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Mozilla/5.0 (X11; Linux x86_64) kde-bing-potd-refresh/{__version__}"},
    )
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            images = data.get("images") or []
            if images:
                return images[0]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(
                f"[kde-bing-potd-refresh] Fetch attempt {attempt}/{attempts} failed: {exc}",
                file=sys.stderr,
            )
            if attempt < attempts:
                time.sleep(delay_sec)
    return None


def _meta_matches_latest(meta: dict[str, Any], startdate: str, urlbase: str) -> bool:
    remote_url = str(meta.get("RemoteUrl", ""))
    info_url = str(meta.get("InfoUrl", ""))
    url_ok = bool(urlbase) and (urlbase in remote_url)
    date_ok = bool(startdate) and (
        f'HpDate%3A%22{startdate}_' in info_url
        or f'HpDate%3a%22{startdate}_' in info_url
        or f'HpDate:"{startdate}_' in info_url
    )
    return url_ok or date_ok


def inspect_local_cache(
    cache_dir: Path,
    startdate: str = "",
    urlbase: str = "",
) -> list[dict[str, Any]]:
    """Inspect all cached bing*.json entries and their paired image files."""
    if not cache_dir.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for jf in sorted(cache_dir.glob("bing*.json")):
        img_file = cache_dir / jf.stem
        image_exists = img_file.is_file()
        image_bytes = img_file.stat().st_size if image_exists else 0
        mtime_iso = (
            datetime.fromtimestamp(jf.stat().st_mtime, tz=timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )
        try:
            meta = json.loads(jf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        matches = (
            image_exists
            and image_bytes > 0
            and bool(meta)
            and _meta_matches_latest(meta, startdate, urlbase)
        )
        entries.append(
            {
                "file": str(jf),
                "image_file": str(img_file),
                "image_exists": image_exists,
                "image_bytes": image_bytes,
                "mtime_iso": mtime_iso,
                "title": str(meta.get("Title", "")),
                "author": str(meta.get("Author", "")),
                "remote_url": str(meta.get("RemoteUrl", "")),
                "info_url": str(meta.get("InfoUrl", "")),
                "matches_latest": matches,
            }
        )
    return entries


def cache_matches_latest(cache_dir: Path, startdate: str, urlbase: str) -> bool:
    """Return True if any non-empty cached bing entry matches today's Bing metadata."""
    return any(entry["matches_latest"] for entry in inspect_local_cache(cache_dir, startdate, urlbase))


def backdate_bing_cache(cache_dir: Path, hours: int = 48) -> list[Path]:
    """Set mtime/atime back by `hours` on bing* cache files so KDE's daysTo() triggers a fetch."""
    touched: list[Path] = []
    if not cache_dir.is_dir():
        return touched
    past = time.time() - (hours * 3600)
    for entry in sorted(cache_dir.glob("bing*")):
        if entry.is_file():
            os.utime(entry, (past, past))
            touched.append(entry)
    return touched


def plasmashell_is_active(qdbus_bin: str) -> bool:
    """Check whether org.kde.plasmashell is reachable on the user session D-Bus."""
    try:
        proc = subprocess.run(
            [qdbus_bin, "org.kde.plasmashell", "/PlasmaShell", "org.freedesktop.DBus.Peer.Ping"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def plasmashell_evaluate(qdbus_bin: str, script: str) -> bool:
    """Execute a PlasmaShell JavaScript snippet over D-Bus."""
    try:
        proc = subprocess.run(
            [qdbus_bin, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _resolve_exec_path(exec_path: str | None = None) -> str:
    if exec_path:
        return exec_path
    on_path = shutil.which("kde-bing-potd-refresh")
    if on_path:
        return str(Path(on_path).resolve())
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 and argv0.exists() and argv0.name == "kde-bing-potd-refresh":
        return str(argv0.resolve())
    return f"{sys.executable} -m kde_bing_potd_refresh"


def _read_bundled_unit(filename: str) -> str:
    data_dir = importlib.resources.files("kde_bing_potd_refresh").joinpath("data")
    return data_dir.joinpath(filename).read_text(encoding="utf-8")


def _run_systemctl_user(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=check,
    )


def install_user_timer(systemd_dir: Path, exec_path: str | None = None) -> int:
    """Install and enable the systemd --user service and timer."""
    resolved_exec = _resolve_exec_path(exec_path)
    service_text = _read_bundled_unit(SERVICE_NAME)
    service_text = re.sub(
        r"^ExecStart=.*$",
        f"ExecStart={resolved_exec}",
        service_text,
        count=1,
        flags=re.MULTILINE,
    )
    timer_text = _read_bundled_unit(TIMER_NAME)

    systemd_dir.mkdir(parents=True, exist_ok=True)
    service_path = systemd_dir / SERVICE_NAME
    timer_path = systemd_dir / TIMER_NAME
    service_path.write_text(service_text, encoding="utf-8")
    timer_path.write_text(timer_text, encoding="utf-8")

    try:
        _run_systemctl_user(["daemon-reload"], check=True)
        _run_systemctl_user(["enable", "--now", TIMER_NAME], check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[kde-bing-potd-refresh] Failed to enable systemd user timer: {exc}", file=sys.stderr)
        return 1

    print(f"[kde-bing-potd-refresh] Installed {service_path} (ExecStart={resolved_exec}) and enabled {TIMER_NAME}.")
    return 0


def uninstall_user_timer(systemd_dir: Path) -> int:
    """Disable and remove the systemd --user service and timer."""
    try:
        _run_systemctl_user(["disable", "--now", TIMER_NAME], check=False)
    except (OSError, subprocess.SubprocessError):
        pass

    removed: list[str] = []
    for unit_name in (SERVICE_NAME, TIMER_NAME):
        unit_path = systemd_dir / unit_name
        if unit_path.exists():
            unit_path.unlink()
            removed.append(str(unit_path))

    try:
        _run_systemctl_user(["daemon-reload"], check=False)
    except (OSError, subprocess.SubprocessError):
        pass

    print(f"[kde-bing-potd-refresh] Uninstalled timer; removed {len(removed)} unit file(s).")
    return 0


def get_timer_status() -> dict[str, Any]:
    """Query systemd --user for kde-bing-potd-refresh.timer state."""
    status: dict[str, Any] = {
        "unit": TIMER_NAME,
        "enabled": "unknown",
        "active_state": "unknown",
        "next_elapse": "",
        "last_trigger": "",
    }
    try:
        enabled_proc = _run_systemctl_user(["is-enabled", TIMER_NAME], check=False)
        status["enabled"] = enabled_proc.stdout.strip() or enabled_proc.stderr.strip() or "unknown"
        show_proc = _run_systemctl_user(
            ["show", TIMER_NAME, "-p", "ActiveState", "-p", "NextElapseUSecRealtime", "-p", "LastTriggerUSec"],
            check=False,
        )
        for line in show_proc.stdout.splitlines():
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key == "ActiveState":
                status["active_state"] = val
            elif key == "NextElapseUSecRealtime":
                status["next_elapse"] = val
            elif key == "LastTriggerUSec":
                status["last_trigger"] = val
    except (OSError, subprocess.SubprocessError) as exc:
        status["error"] = str(exc)
    return status


def _emit_result(payload: dict[str, Any], as_json: bool, human_message: str | None = None) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
    elif human_message:
        print(human_message)


def run_status(cache_dir: Path, market: str | None, as_json: bool) -> int:
    """Inspect live Bing API, local POTD cache, and systemd timer without modifying anything."""
    latest = fetch_latest_bing_meta(market=market, retries=1)
    startdate = str(latest.get("startdate", "")) if latest else ""
    urlbase = str(latest.get("urlbase", "")) if latest else ""
    cache_entries = inspect_local_cache(cache_dir, startdate, urlbase)
    in_sync = any(entry["matches_latest"] for entry in cache_entries) if latest else False
    timer = get_timer_status()

    payload = {
        "version": __version__,
        "market": (market or "").strip() or "auto",
        "cache_dir": str(cache_dir),
        "bing_latest": (
            {
                "startdate": startdate,
                "fullstartdate": latest.get("fullstartdate", ""),
                "title": latest.get("title", ""),
                "copyright": latest.get("copyright", ""),
                "urlbase": urlbase,
            }
            if latest
            else None
        ),
        "in_sync": in_sync,
        "cache_entries": cache_entries,
        "timer": timer,
    }

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"kde-bing-potd-refresh v{__version__}")
        if latest:
            print(f"Bing Latest : {startdate} — {latest.get('title', '')!r}")
        else:
            print("Bing Latest : unavailable (network offline or API unreachable)")
        print(f"In Sync     : {'yes' if in_sync else 'no'}")
        print(f"Cache Dir   : {cache_dir}")
        if cache_entries:
            for entry in cache_entries:
                flag = "MATCH" if entry["matches_latest"] else "STALE"
                print(
                    f"  - [{flag}] {Path(entry['file']).name}: "
                    f"{entry['title']!r} (mtime={entry['mtime_iso']}, image={entry['image_bytes']} bytes)"
                )
        else:
            print("  - (no bing*.json cache files found)")
        print(
            f"Timer       : {timer['unit']} (enabled={timer['enabled']}, "
            f"active={timer['active_state']}, next={timer['next_elapse'] or 'n/a'})"
        )
    return 0


def run_sync(
    cache_dir: Path,
    market: str | None,
    force: bool,
    as_json: bool,
) -> int:
    """Check Bing feed and refresh Plasma POTD if local cache is behind."""
    latest = fetch_latest_bing_meta(market=market)
    if not latest:
        msg = "[kde-bing-potd-refresh] Could not reach Bing API; leaving existing cache intact."
        print(msg, file=sys.stderr)
        if as_json:
            _emit_result({"status": "unreachable", "updated": False}, True)
        return 0

    startdate = str(latest.get("startdate", ""))
    urlbase = str(latest.get("urlbase", ""))
    title = str(latest.get("title", ""))

    if not force and cache_matches_latest(cache_dir, startdate, urlbase):
        msg = f"[kde-bing-potd-refresh] Cache already matches Bing {startdate} ({title!r}); nothing to do."
        _emit_result(
            {"status": "up_to_date", "updated": False, "startdate": startdate, "title": title},
            as_json,
            msg,
        )
        return 0

    touched = backdate_bing_cache(cache_dir)
    if not as_json:
        reason = "Forced refresh" if force else f"Cache stale vs Bing {startdate} ({title!r})"
        print(f"[kde-bing-potd-refresh] {reason}; backdated {len(touched)} file(s).")

    qdbus_bin = find_qdbus_bin()
    if not qdbus_bin or not plasmashell_is_active(qdbus_bin):
        msg = "[kde-bing-potd-refresh] plasmashell is not active; it will fetch fresh wallpaper on next start."
        _emit_result(
            {
                "status": "backdated_no_plasmashell",
                "updated": False,
                "startdate": startdate,
                "title": title,
                "backdated_files": len(touched),
            },
            as_json,
            msg,
        )
        return 0

    if not plasmashell_evaluate(qdbus_bin, JS_CLEAR_BING):
        print("[kde-bing-potd-refresh] Warning: failed to clear Provider via plasmashell D-Bus.", file=sys.stderr)
        return 1

    # Give Qt's event loop a moment to unregister the old PotdClient before re-registering "bing"
    time.sleep(0.7)

    if not plasmashell_evaluate(qdbus_bin, JS_RESTORE_BING):
        print("[kde-bing-potd-refresh] Error: failed to restore Provider='bing' via plasmashell D-Bus.", file=sys.stderr)
        return 1

    # Wait up to 15s for PotdBackend to finish downloading and updating the cache metadata
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if cache_matches_latest(cache_dir, startdate, urlbase):
            msg = f"[kde-bing-potd-refresh] Successfully updated wallpaper to {startdate}: {title!r}."
            _emit_result(
                {
                    "status": "updated",
                    "updated": True,
                    "startdate": startdate,
                    "title": title,
                    "backdated_files": len(touched),
                },
                as_json,
                msg,
            )
            return 0
        time.sleep(0.5)

    msg = "[kde-bing-potd-refresh] Triggered refresh, but cache did not finish updating within 15s."
    print(msg, file=sys.stderr)
    if as_json:
        _emit_result(
            {
                "status": "triggered_pending",
                "updated": False,
                "startdate": startdate,
                "title": title,
                "backdated_files": len(touched),
            },
            True,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="kde-bing-potd-refresh",
        description=(
            "Synchronize KDE Plasma 6 Bing Picture of the Day (org.kde.potd) after "
            "Bing rotates at 00:00 America/Los_Angeles."
        ),
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-s",
        "--status",
        "--check",
        action="store_true",
        dest="status",
        help="Show live Bing metadata, local POTD cache state, and systemd timer status without modifying files",
    )
    mode_group.add_argument(
        "--install-timer",
        action="store_true",
        help="Install and enable the systemd --user service and timer",
    )
    mode_group.add_argument(
        "--uninstall-timer",
        action="store_true",
        help="Disable and remove the systemd --user service and timer",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force backdating cache and refreshing plasmashell even when cache matches latest",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output for --status or sync runs",
    )
    parser.add_argument(
        "--market",
        default=os.environ.get("BING_POTD_MARKET", ""),
        help="Optional Bing market code (e.g. en-US, en-GB, de-DE; defaults to BING_POTD_MARKET or auto)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Override KDE POTD cache directory (default: ~/.cache/plasma_engine_potd)",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    cache_dir = args.cache_dir if args.cache_dir is not None else get_default_cache_dir()
    systemd_dir = get_default_systemd_user_dir()

    if args.install_timer:
        return install_user_timer(systemd_dir)
    if args.uninstall_timer:
        return uninstall_user_timer(systemd_dir)
    if args.status:
        return run_status(cache_dir=cache_dir, market=args.market, as_json=args.json)
    return run_sync(cache_dir=cache_dir, market=args.market, force=args.force, as_json=args.json)
