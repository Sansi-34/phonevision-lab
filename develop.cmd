@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\local_tasks.ps1" -Task Shell
