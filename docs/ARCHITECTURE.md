# Architecture & KDE Plasma 6 Internals

This document details how `org.kde.potd` caches and schedules Bing Picture of the Day wallpapers in KDE Plasma 6, and why `kde-bing-potd-refresh` uses cache backdating + two-phase `evaluateScript` D-Bus reloads.

---

## 1. KDE Plasma `PotdEngine` Behavior (`kdeplasma-addons`)

KDE's Picture of the Day wallpaper plugin (`/usr/share/plasma/wallpapers/org.kde.potd/contents/ui/main.qml`) instantiates a `PotdBackend` QML object (`libplasma_wallpaper_potdplugin.so`) backed by `PotdEngine` and `CachedProvider`:

| Component | Behavior | Impact |
| :--- | :--- | :--- |
| **`PotdEngine` midnight timer** | Schedules daily refresh at `00:01` local system time (`QDate::currentDate().addDays(1).startOfDay()`) | On `America/New_York`, fires at `21:01` Pacific Time—3 hours before Bing rotates |
| **`CachedProvider::isCached()`** | Compares `QFileInfo::fileTime()` against `QDateTime::currentDateTime()` using `daysTo() == 0` | Once Bing's previous-day photo is saved at `00:01` EST, KDE treats the cache as valid all day |
| **`PotdEngine::slotPrepareForSleep(bool)`** | Calls `PotdEngine::updateSource(true)` on wake from sleep | Still skips downloading if `CachedProvider` already has today's `mtime` |
| **QML `arguments` resolution selector** | Passes `[]`, `[1920, 1080]`, `[3840, 2160]`, or `[1080, 1920]` to `plasma_potd_bingprovider.so` | Creates dimension-suffixed files such as `bing:3840:2160` + `bing:3840:2160.json` |

---

## 2. Why Two-Phase `evaluateScript` Toggling Is Used

1. **QML property binding coalescing**:
   Executing `d.writeConfig("Provider", ""); d.writeConfig("Provider", "bing");` in a single `org.kde.PlasmaShell.evaluateScript` call causes Qt/QML to coalesce the synchronous config updates within the same event loop tick, so `PotdBackend::setIdentifier()` never observes a transition and `PotdClient` stays attached to the in-memory `QImage`.
2. **Explicit `0.7s` separation**:
   Clearing `Provider` to `""` in one D-Bus call, waiting `0.7s` for `PotdEngine::unregisterClient()` to run, and restoring `Provider="bing"` in a second D-Bus call reliably triggers `PotdBackend::registerClient()` and reloads the freshly fetched UHD wallpaper through KDE's `QQC2.StackView` cross-fade transition.
3. **Why `os.utime()` backdating is safer than `rm`**:
   Setting `mtime` back 48 hours (`time.time() - 172800`) makes `CachedProvider` treat the cache as stale without deleting the file. If Bing is briefly unreachable during reload, KDE retains the prior image rather than flashing a solid black background.

---

## 3. DST-Safe `systemd --user` Calendar Scheduling

```ini
OnCalendar=*-*-* 00:05:00 America/Los_Angeles
OnCalendar=*-*-* 00:35:00 America/Los_Angeles
OnStartupSec=45s
Persistent=true
```

- Using `America/Los_Angeles` directly in `OnCalendar=` instructs `systemd` to track Pacific Standard Time (`UTC-8`) and Pacific Daylight Time (`UTC-7`) automatically, firing at `03:05` / `03:35` Eastern year-round (and `02:05` / `02:35` Central, `01:05` / `01:35` Mountain).
- The secondary `:35` run guards against rare CDN propagation delays on Bing's edge nodes (`HPImageArchive.aspx` vs `_UHD.jpg` image availability).
- `Persistent=true` + `OnStartupSec=45s` catches missed updates if the workstation was asleep or powered off overnight.
