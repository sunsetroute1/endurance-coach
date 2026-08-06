# Jellyfin FFmpeg 9 integration for Windows.
# Detects CPU/GPU and can auto-tune encoding.xml, or use -ManualConfig for FFmpeg path only.
# Run Install-JellyfinFfmpeg9.ps1 -Action Install (elevated).
@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-JellyfinFfmpeg9.ps1" -Action Install %*
if errorlevel 1 (
  echo.
  echo Install failed. See C:\ProgramData\Jellyfin\logs\jellyfin-ffmpeg9-install.log
  pause
  exit /b 1
)
echo.
echo Done. Jellyfin is configured to use FFmpeg 9 at C:\FFmpeg9\bin\ffmpeg.exe
echo.
echo After a Jellyfin update, run Repair.cmd in this folder.
pause