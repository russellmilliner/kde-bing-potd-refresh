# Troubleshooting Guide

## 1. Check Sync State Without Modifying Anything

Run `--status` (or `--status --json`) to compare Bing's live API against your local `~/.cache/plasma_engine_potd/` entries and `systemd --user` timer:

```bash
kde-bing-potd-refresh --status
kde-bing-potd-refresh --status --json
```

---

## 2. Leftover Multi-Resolution Cache Files (`bing:1920:1080` vs `bing:3840:2160`)

If you previously connected a `1920x1080` monitor or changed display scaling, `~/.cache/plasma_engine_potd/` may contain an older `bing:1920:1080` / `bing:1920:1080.json` pair alongside your current `bing:3840:2160` cache.

- `kde-bing-potd-refresh` checks whether **any** non-empty `bing*.json` entry matches today's Bing metadata, so abandoned resolution caches will not trigger false stale reloads.
- You can inspect all cached files with:
  ```bash
  ls -lh ~/.cache/plasma_engine_potd/
  ```

---

## 3. Wallpaper Doesn't Update Over a Metered Connection

KDE Plasma's `org.kde.potd` respects the **"Update over metered connection"** setting (`UpdateOverMeteredConnection` in `~/.config/plasma-org.kde.plasma.desktop-appletsrc`). If your network interface is marked metered in NetworkManager, `PotdEngine` refuses to download images even when triggered by `kde-bing-potd-refresh`.

Check your containment settings via D-Bus:

```bash
qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.wallpaper 0
```

If `UpdateOverMeteredConnection: 0` and your connection is metered, enable **"Update wallpaper over metered connection"** in **Desktop and Wallpaper → Picture of the Day**.

---

## 4. Network Still Settling After Wake or Boot

When waking from suspend or booting over Wi-Fi, `kde-bing-potd-refresh` retries Bing API requests up to 6 times with a 5-second delay (`~25s` total) before exiting cleanly so `systemd` never marks the unit failed while offline. Check logs with:

```bash
journalctl --user -u kde-bing-potd-refresh.service -n 30 --no-pager
```

---

## 5. Using a Non-US Bing Market

By default, Bing routes `HPImageArchive.aspx` by GeoIP. To pin a specific Bing market (for example `en-US`, `en-GB`, `ja-JP`, or `de-DE`), pass `--market` or set `BING_POTD_MARKET` in a systemd drop-in override:

```bash
systemctl --user edit kde-bing-potd-refresh.service
```

```ini
[Service]
Environment=BING_POTD_MARKET=en-US
```
