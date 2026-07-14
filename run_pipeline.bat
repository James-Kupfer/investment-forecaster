@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_pipeline.ps1"
if errorlevel 1 (
    echo.
    echo Pipeline exited with errors.
    pause
)
