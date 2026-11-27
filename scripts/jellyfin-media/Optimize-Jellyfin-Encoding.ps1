# Legacy alias — applies the Jellyfin QSV + FFmpeg 9 encoding profile.
#Requires -RunAsAdministrator
& (Join-Path $PSScriptRoot 'Install-JellyfinFfmpeg9.ps1') -Action Repair -SkipDeploy -SkipFfmpegDownload @args
