@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\start-ai-office.ps1"
if errorlevel 1 pause
