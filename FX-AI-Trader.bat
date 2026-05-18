@echo off
cd /d C:\Users\mao\Desktop\fx-trader-desktop\src-python
start "" /b C:\Users\mao\Desktop\fx-trader-desktop\.venv\Scripts\python.exe -m uvicorn api.server:app --host 127.0.0.1 --port 8742
cd /d C:\Users\mao\Desktop\fx-trader-desktop
start "" /b cmd /c "npm run dev"
timeout /t 10 /nobreak > nul
C:\Users\mao\Desktop\fx-trader-desktop\src-tauri\target\debug\fx-trader-desktop.exe
