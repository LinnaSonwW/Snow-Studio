@echo off
cd /d %~dp0
set "FLUIDSYNTH_HOME=%~dp0runtime\fluidsynth"
set "PATH=%~dp0runtime\fluidsynth;%~dp0runtime\ffmpeg;%PATH%"
start "" python\python.exe app\бнЪО.py
