# Native Windows Music Ingestion Pipeline

End-to-end flow for a **non-Docker** Windows 11 media server:

```
slskd
  -> E:\Music\Incoming\Soulseek
  -> Python watchdog (debounced)
  -> beets (MusicBrainz tagging + art + scrub + dedupe + replaygain)
  -> E:\Music\Library
  -> Navidrome (scan every 1m)
  -> Jellyfin (optional music library; video stays on E:\Video)
```

## Automation approach comparison

| Approach | Reliability | Real-time | Maintenance | Verdict |
|----------|-------------|-----------|-------------|---------|
| **PowerShell FileSystemWatcher** | Medium | Yes | Low | Native, but buffers overflow under burst downloads and long-running watchers are fragile on Windows. |
| **Python watchdog** | High | Yes | Low | Best fit: stable recursive watching, debouncing, integrates directly with beets, easy logging. **Chosen primary.** |
| **Windows Task Scheduler (periodic)** | High | No (delayed) | Very low | Excellent safety net for missed events. **Chosen fallback (every 30 min).** |
| **Windows Service (NSSM/pywin32)** | Highest | Yes | Medium | Best always-on semantics, but adds another install layer. Optional upgrade; scheduled task matches your existing stack. |

**Selected architecture:** Python `watchdog` daemon + **Scheduled Task at startup** + **30-minute fallback scan**.

---

## Directory layout (`E:\Music` media root)

```
E:\Music\
├── Incoming\
│   └── Soulseek\              # slskd completed downloads
│       └── incomplete\        # slskd partial downloads
├── Library\                   # beets output; Navidrome scans here
├── Quarantine\                # manual holding area for failed imports
└── State\
    ├── beets-library.blb      # beets database
    ├── beets-import.log       # beets import log
    ├── processed-paths.json   # watcher idempotency state
    └── pending-imports.json   # reserved
```

> **Note:** Your original diagram used `D:\Media\...`. This server uses **`E:\Music`** as the media root, so paths are mapped accordingly.

---

## Install steps

### 1. One-shot installer

```powershell
cd C:\Users\adminnie\Projects\endurance-coach
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\music-ingest\install_music_ingest.ps1
```

This will:

- Create `E:\Music\Incoming\Soulseek`, `Library`, `Quarantine`, `State`
- Create `services\music-ingest\.venv` and install `beets` + `watchdog`
- Install `%APPDATA%\beets\config.yaml`
- Copy `services\music-ingest\config\pipeline.env` (if missing)
- Point slskd downloads to `E:\Music\Incoming\Soulseek`
- Point Navidrome to `E:\Music\Library`
- Register scheduled tasks:
  - `MusicIngestWatcher` (startup +90s)
  - `MusicIngestFallbackScan` (every 30 min)

### 2. Restart services

```powershell
Stop-Process -Name slskd -Force -ErrorAction SilentlyContinue
powershell -File .\scripts\start_slskd_windows.ps1

Stop-Process -Name navidrome -Force -ErrorAction SilentlyContinue
# Navidrome task will restart on reboot; or start manually:
C:\Navidrome\navidrome.exe --configfile C:\Navidrome\navidrome.toml

powershell -File .\scripts\music-ingest\start_music_watcher.ps1
```

### 3. Migrate existing loose downloads (optional)

Move current Soulseek folders/files from `E:\Music\` root into `E:\Music\Incoming\Soulseek\`, excluding `Library`, `Incoming`, `State`, `Quarantine`.

---

## Python requirements

File: `services/music-ingest/requirements.txt`

```
beets>=2.0.0
watchdog>=6.0.0
```

Installed into: `services\music-ingest\.venv`

---

## beets configuration

Template: `services/music-ingest/config/beets-config.yaml`

Installed to: `%APPDATA%\beets\config.yaml`

Enabled plugins:

| Plugin | Purpose |
|--------|---------|
| `fetchart` | Download cover art (MusicBrainz / Cover Art Archive) |
| `embedart` | Embed art into audio tags |
| `scrub` | Clean up tags (remove junk fields) |
| `duplicates` | Detect duplicate tracks/albums |
| `badfiles` | Reject/truncate corrupt audio on import |
| `replaygain` | Optional — enable after installing `mp3gain` on PATH (see below) |

Import behavior:

- **move** from incoming -> library (keeps incoming clean)
- **autotag** via MusicBrainz
- path template: `$albumartist/$album%aunique{}/$track $title`

Manual commands:

```powershell
$beet = "C:\Users\adminnie\Projects\endurance-coach\services\music-ingest\.venv\Scripts\beet.exe"
& $beet import -m "E:\Music\Incoming\Soulseek\Some\Album"
& $beet ls
& $beet stats
```

---

## Automation scripts

| Script | Purpose |
|--------|---------|
| `scripts/music-ingest/setup_music_directories.ps1` | Create folder layout |
| `scripts/music-ingest/install_music_ingest.ps1` | Full installer |
| `scripts/music-ingest/start_music_watcher.ps1` | Start watchdog daemon |
| `scripts/music-ingest/run_beets_import.ps1` | One-shot scan/import |
| `scripts/music-ingest/install_music_watcher_startup.ps1` | Register startup task |
| `scripts/music-ingest/install_music_ingest_fallback.ps1` | Register 30-min fallback task |
| `scripts/music-ingest/rollback_music_ingest.ps1` | Remove tasks + stop watcher |

Core Python:

| File | Purpose |
|------|---------|
| `services/music-ingest/src/watcher.py` | Filesystem watcher + debounce |
| `services/music-ingest/src/beets_runner.py` | beets subprocess + idempotency |
| `services/music-ingest/src/pipeline_config.py` | Paths + ignore rules |

---

## Logging

| Log | Location |
|-----|----------|
| Watcher/application | `logs/music-ingest.log` |
| Watcher stdout/stderr | `logs/music-ingest.stdout.log`, `logs/music-ingest.stderr.log` |
| beets import log | `E:\Music\State\beets-import.log` |
| Process PID | `logs/music-ingest.pid` |

Watcher waits **120 seconds** after the last file change before importing (configurable in `pipeline.env`).

---

## Rollback plan

```powershell
powershell -File .\scripts\music-ingest\rollback_music_ingest.ps1
```

Then manually restore if desired:

1. `C:\slskd\data\slskd.yml` -> downloads `E:\Music`, shares `E:\Music`
2. `C:\Navidrome\navidrome.toml` -> `MusicFolder = "E:\\Music"`
3. Remove `services\music-ingest\.venv`
4. Remove `%APPDATA%\beets\config.yaml` (optional)

Existing files in `E:\Music\Library` are preserved.

---

## Testing checklist

- [ ] **Directories exist:** `E:\Music\Incoming\Soulseek`, `Library`, `State`
- [ ] **beets installed:** `.venv\Scripts\beet.exe version`
- [ ] **slskd paths:** downloads -> `Incoming\Soulseek`, incomplete -> `Incoming\Soulseek\incomplete`
- [ ] **Navidrome path:** `MusicFolder = E:\Music\Library`
- [ ] **Watcher running:** `Get-Content logs\music-ingest.pid` + process alive
- [ ] **Scheduled tasks:** `MusicIngestWatcher`, `MusicIngestFallbackScan` in Task Scheduler
- [ ] **Drop test album:** copy a tagged album folder into `Incoming\Soulseek\TestArtist\TestAlbum`
- [ ] **Wait 2+ minutes** with no file changes
- [ ] **Verify import:** album appears under `E:\Music\Library\...`
- [ ] **Verify Navidrome:** album visible at `music.santajellyfe.duckdns.org` within ~1 min
- [ ] **Check logs:** no errors in `logs/music-ingest.log` or `E:\Music\State\beets-import.log`
- [ ] **Fallback scan:** `powershell -File .\scripts\music-ingest\run_beets_import.ps1`
- [ ] **Unit tests:** `python -m pytest tests/test_music_ingest_pipeline.py`

---

## Optional: enable replaygain

beets replaygain on Windows requires **mp3gain** on PATH:

```powershell
winget install --id GlenSawyer.MP3Gain -e
```

Then uncomment the `replaygain` block in `services/music-ingest/config/beets-config.yaml`, add `replaygain` to the `plugins` list, and redeploy:

```powershell
Copy-Item .\services\music-ingest\config\beets-config.yaml $env:APPDATA\beets\config.yaml -Force
```

---

Current Jellyfin libraries point to `E:\Video\` only (movies/TV). To surface music in Jellyfin, add a **Music** library pointing to `E:\Music\Library` in the Jellyfin dashboard. Navidrome already uses the same folder.

---

## Optional hardening

- **Windows Service via NSSM:** wrap `start_music_watcher.ps1` for faster recovery than scheduled-task restart intervals.
- **mp3gain binary:** improves replaygain coverage for older MP3 files (beets falls back to R128/FFmpeg where possible).
- **Quarantine workflow:** failed imports can be moved manually to `E:\Music\Quarantine` for inspection.
