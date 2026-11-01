@echo off
rem Starts the input-fix helper (silent, no window) and then the game.
cd /d "%~dp0"
if exist "GekkouInputFix.exe" start "" "GekkouInputFix.exe"
if exist "GekkounoCarnevale.exe" (
  start "" "GekkounoCarnevale.exe"
) else (
  echo Place this file next to GekkounoCarnevale.exe
  pause
)
