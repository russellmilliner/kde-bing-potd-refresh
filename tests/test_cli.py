"""Unit tests for kde_bing_potd_refresh.cli."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import time
from unittest.mock import patch
import urllib.error

import pytest

from kde_bing_potd_refresh import __version__, cli


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _sample_bing_api(
    startdate: str = "20261115",
    urlbase: str = "/th?id=OHR.FirstFrost_EN-US8881008245",
    title: str = "Frosty foliage",
) -> dict:
    return {
        "images": [
            {
                "startdate": startdate,
                "fullstartdate": f"{startdate}0800",
                "enddate": "20261116",
                "url": f"{urlbase}_1920x1080.jpg",
                "urlbase": urlbase,
                "copyright": "Azaleas (c) avoferten/Shutterstock",
                "copyrightlink": f"https://www.bing.com/search?q=azaleas&form=hpcapt&filters=HpDate%3A%22{startdate}_0800%22",
                "title": title,
            }
        ]
    }


def _write_potd_entry(
    cache_dir: Path,
    stem: str,
    startdate: str,
    urlbase: str,
    title: str,
    image_bytes: bytes = b"fake-jpeg-data",
) -> tuple[Path, Path]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    img_path = cache_dir / stem
    json_path = cache_dir / f"{stem}.json"
    img_path.write_bytes(image_bytes)
    json_path.write_text(
        json.dumps(
            {
                "Author": "Tester",
                "InfoUrl": f"https://www.bing.com/search?q=test&filters=HpDate%3A%22{startdate}_0800%22",
                "RemoteUrl": f"https://www.bing.com/{urlbase}_UHD.jpg",
                "Title": title,
            }
        ),
        encoding="utf-8",
    )
    return img_path, json_path


def test_cache_matches_latest_ignores_abandoned_resolution(tmp_path: Path) -> None:
    _write_potd_entry(
        tmp_path,
        "bing:1920:1080",
        "20260709",
        "/th?id=OHR.SapaVietnam_EN-US4008171614",
        "Tradition in every step",
    )
    _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
        "Frosty foliage",
    )

    assert cli.cache_matches_latest(
        tmp_path,
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
    )


def test_cache_matches_latest_false_when_stale_or_empty(tmp_path: Path) -> None:
    _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261114",
        "/th?id=OHR.Yesterday_EN-US0000000001",
        "Yesterday",
    )
    assert not cli.cache_matches_latest(
        tmp_path,
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
    )

    _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
        "Frosty foliage",
        image_bytes=b"",
    )
    assert not cli.cache_matches_latest(
        tmp_path,
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
    )


def test_backdate_bing_cache_only_touches_bing_files(tmp_path: Path) -> None:
    bing_img, bing_json = _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261114",
        "/th?id=OHR.Old_EN-US1",
        "Old",
    )
    apod_img = tmp_path / "apod"
    apod_img.write_bytes(b"apod-data")
    now = time.time()
    os.utime(apod_img, (now, now))
    apod_mtime_before = apod_img.stat().st_mtime

    touched = cli.backdate_bing_cache(tmp_path, hours=48)
    assert set(touched) == {bing_img, bing_json}
    assert bing_img.stat().st_mtime < now - (47 * 3600)
    assert bing_json.stat().st_mtime < now - (47 * 3600)
    assert apod_img.stat().st_mtime == apod_mtime_before


def test_main_noop_when_already_synced(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
        "Frosty foliage",
    )
    api_payload = _sample_bing_api()

    with (
        patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(api_payload)),
        patch("subprocess.run") as mock_run,
    ):
        rc = cli.main(["--cache-dir", str(tmp_path)])

    assert rc == 0
    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "nothing to do" in out


def test_main_stale_cache_backdates_and_toggles_provider(tmp_path: Path) -> None:
    _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261114",
        "/th?id=OHR.Yesterday_EN-US1",
        "Yesterday",
    )
    api_payload = _sample_bing_api()
    eval_scripts: list[str] = []

    def fake_subprocess_run(cmd, **kwargs):
        if "org.freedesktop.DBus.Peer.Ping" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "org.kde.PlasmaShell.evaluateScript" in cmd:
            script = cmd[-1]
            eval_scripts.append(script)
            if 'd.writeConfig("Provider", "bing")' in script:
                _write_potd_entry(
                    tmp_path,
                    "bing:3840:2160",
                    "20261115",
                    "/th?id=OHR.FirstFrost_EN-US8881008245",
                    "Frosty foliage",
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    with (
        patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(api_payload)),
        patch("kde_bing_potd_refresh.cli.find_qdbus_bin", return_value="/usr/bin/qdbus6"),
        patch("subprocess.run", side_effect=fake_subprocess_run),
        patch("time.sleep"),
    ):
        rc = cli.main(["--cache-dir", str(tmp_path)])

    assert rc == 0
    assert len(eval_scripts) == 2
    assert 'd.writeConfig("Provider", "")' in eval_scripts[0]
    assert 'd.writeConfig("Provider", "bing")' in eval_scripts[1]


def test_main_force_refreshes_even_when_current(tmp_path: Path) -> None:
    _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
        "Frosty foliage",
    )
    api_payload = _sample_bing_api()
    eval_calls = 0

    def fake_subprocess_run(cmd, **kwargs):
        nonlocal eval_calls
        if "org.freedesktop.DBus.Peer.Ping" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "org.kde.PlasmaShell.evaluateScript" in cmd:
            eval_calls += 1
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    with (
        patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(api_payload)),
        patch("kde_bing_potd_refresh.cli.find_qdbus_bin", return_value="/usr/bin/qdbus6"),
        patch("subprocess.run", side_effect=fake_subprocess_run),
        patch("time.sleep"),
    ):
        rc = cli.main(["--cache-dir", str(tmp_path), "--force"])

    assert rc == 0
    assert eval_calls == 2


def test_main_handles_unreachable_bing_gracefully(tmp_path: Path) -> None:
    with (
        patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")),
        patch("time.sleep"),
    ):
        rc = cli.main(["--cache-dir", str(tmp_path)])

    assert rc == 0


def test_status_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_potd_entry(
        tmp_path,
        "bing:3840:2160",
        "20261115",
        "/th?id=OHR.FirstFrost_EN-US8881008245",
        "Frosty foliage",
    )
    api_payload = _sample_bing_api()

    def fake_subprocess_run(cmd, **kwargs):
        if "is-enabled" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="enabled\n", stderr="")
        if "show" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="ActiveState=active\nNextElapseUSecRealtime=Mon 2026-11-16 03:05:00 EST\nLastTriggerUSec=Sun 2026-11-15 03:35:05 EST\n",
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {cmd}")

    with (
        patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(api_payload)),
        patch("subprocess.run", side_effect=fake_subprocess_run),
    ):
        rc = cli.main(["--cache-dir", str(tmp_path), "--status", "--json"])

    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["version"] == __version__
    assert parsed["in_sync"] is True
    assert parsed["bing_latest"]["startdate"] == "20261115"
    assert parsed["timer"]["enabled"] == "enabled"
    assert len(parsed["cache_entries"]) == 1


def test_install_and_uninstall_user_timer(tmp_path: Path) -> None:
    systemd_dir = tmp_path / "systemd-user"
    commands: list[list[str]] = []

    def fake_subprocess_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        rc_install = cli.install_user_timer(systemd_dir, exec_path="/opt/bin/kde-bing-potd-refresh")
        assert rc_install == 0
        service_content = (systemd_dir / cli.SERVICE_NAME).read_text(encoding="utf-8")
        timer_content = (systemd_dir / cli.TIMER_NAME).read_text(encoding="utf-8")
        assert "ExecStart=/opt/bin/kde-bing-potd-refresh" in service_content
        assert "America/Los_Angeles" in timer_content

        rc_uninstall = cli.uninstall_user_timer(systemd_dir)
        assert rc_uninstall == 0
        assert not (systemd_dir / cli.SERVICE_NAME).exists()
        assert not (systemd_dir / cli.TIMER_NAME).exists()

    assert ["systemctl", "--user", "enable", "--now", cli.TIMER_NAME] in commands
    assert ["systemctl", "--user", "disable", "--now", cli.TIMER_NAME] in commands


def test_build_bing_api_url_with_market() -> None:
    assert cli.build_bing_api_url("") == cli.DEFAULT_BING_API_URL
    assert cli.build_bing_api_url("en-US") == f"{cli.DEFAULT_BING_API_URL}&mkt=en-US"
