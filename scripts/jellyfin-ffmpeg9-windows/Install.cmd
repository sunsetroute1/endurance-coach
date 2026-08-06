@echo off
setlocal
cd /d "%~dp0"
echo Jellyfin FFmpeg 9 for Windows
echo.
echo This will request administrator access, download FFmpeg 9, detect your CPU/GPU,
echo and configure Jellyfin to use it. You can choose auto hardware tuning or manual mode.
echo.
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
