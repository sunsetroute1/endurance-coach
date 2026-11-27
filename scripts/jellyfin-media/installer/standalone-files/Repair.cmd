@echo off
setlocal
cd /d "%~dp0"
echo Re-applying Jellyfin FFmpeg 9 settings...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-JellyfinFfmpeg9.ps1" -Action Repair %*
if errorlevel 1 (
  echo.
  echo Repair failed. See C:\ProgramData\Jellyfin\logs\jellyfin-ffmpeg9-install.log
  pause
  exit /b 1
)
echo.
echo Repair complete.
pause
