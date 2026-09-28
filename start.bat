@echo off
cd /d "%~dp0"
echo Installing requirements (first run only takes a minute)...
python -m pip install -q -r requirements.txt
echo.
echo AdPulse is starting. Open http://localhost:8000  (demo login: demo@agency.test / demo1234)
echo Close this window to stop the site.
start "" http://localhost:8000
python -m uvicorn app.main:app --port 8000
pause
