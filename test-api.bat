@echo off
cd /d %~dp0
cd src-python
..\\.venv\\Scripts\\python.exe -m uvicorn api.server:app --host 127.0.0.1 --port 8742
pause
