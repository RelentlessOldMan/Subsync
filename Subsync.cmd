@echo off
title Subsync
cd /d "%~dp0"
rem Launch windowless (no console). Drag an .srt onto this file to pre-load it.
start "" pythonw subsync.py %*
