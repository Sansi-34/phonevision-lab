@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local_tasks.ps1" -Task Portable %*
if errorlevel 1 pause
