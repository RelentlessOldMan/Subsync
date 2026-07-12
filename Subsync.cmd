@echo off
title Subsync
cd /d "%~dp0"
rem Subsync -- always-on-top .srt -> keystroke player for synced lyrics.
rem Double-click to launch (windowless, no console). Drag an .srt onto this
rem file to pre-load that song.

where pythonw >nul 2>&1 && (
    start "" pythonw "%~dp0subsync.py" %*
    exit /b
)
where python >nul 2>&1 && (
    start "" python "%~dp0subsync.py" %*
    exit /b
)

echo.
echo   Python was not found on your PATH.
echo   Install Python 3.8+ from https://www.python.org/downloads/
echo   ^(tick "Add python.exe to PATH" during setup^), then run this again.
echo.
pause
