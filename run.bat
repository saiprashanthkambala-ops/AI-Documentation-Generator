@echo off
cd /d "%~dp0"
venv\Scripts\uvicorn.exe backend.main:app --reload --host 0.0.0.0 --port 8000
