# Jellyfin FFmpeg 9 for Windows

Install upstream [FFmpeg 9](https://www.gyan.dev/ffmpeg/builds/) for native Jellyfin on Windows, without replacing Jellyfin's bundled binaries. The installer detects your CPU and GPU and can auto-tune transcoding settings for Intel QSV, NVIDIA NVENC, AMD AMF, or software fallback.

**Repository:** https://github.com/sunsetroute1/jellyfin-ffmpeg9-windows

## Requirements

- Windows 10 or 11
- Jellyfin server installed (native Windows tray/service build, not Docker)
- Administrator access for install/repair

## Quick start

1. Download and extract this folder anywhere (for example `Downloads\jellyfin-ffmpeg9-windows`).
2. Double-click **`Install.cmd`** and approve the UAC prompt.
3. When prompted, choose:
   - **Y** — auto-tune `encoding.xml` for your hardware (recommended)
   - **N** — manual mode: set only the custom FFmpeg path and keep your Dashboard settings

FFmpeg is installed to `C:\FFmpeg9`. Program files are copied to `C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9` so settings survive reboots.

## After a Jellyfin update

Jellyfin updates can reset the custom FFmpeg path. Run **`Repair.cmd`** (or `Repair-Jellyfin-Ffmpeg9.ps1`) as administrator.

Repair is idempotent: if the FFmpeg 9 patch is already active and nothing drifted, it **preserves your existing `encoding.xml` settings** and does not restart Jellyfin unnecessarily. When something did drift (usually the FFmpeg path), only the missing keys are restored — not the full profile.

## Command-line options

Run from PowerShell as administrator:

```powershell
# FFmpeg path only; no transcoding changes
.\Install-JellyfinFfmpeg9.ps1 -ManualConfig

# Auto-tune without the interactive prompt
.\Install-JellyfinFfmpeg9.ps1 -AutoTune

# Check status
.\Install-JellyfinFfmpeg9.ps1 -Action Test

# JSON status (for scripts; exit code 1 if repair needed)
.\Install-JellyfinFfmpeg9.ps1 -Action Test -Json
```

## Logs and backups

| Path | Purpose |
|------|---------|
| `C:\ProgramData\Jellyfin\logs\jellyfin-ffmpeg9-install.log` | Install/repair log |
| `C:\ProgramData\Jellyfin\backups\encoding-optimize\` | Backups of `encoding.xml` before changes |
| `C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9\user.config.json` | Saved auto vs manual mode |

## Verify

Force a transcode (lower quality or remote stream). In Jellyfin Dashboard → **Active Devices**, the method should show hardware transcoding when auto-tune selected a GPU path.

## What this does not do

- Does not modify Jellyfin's bundled `ffmpeg.exe` in `Program Files\Jellyfin\Server`
- Does not require Docker, Watchboard, or any other tooling
- Does not change Jellyfin itself — only FFmpeg on disk and `encoding.xml`
