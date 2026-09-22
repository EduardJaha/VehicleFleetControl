@echo off
setlocal
set "ROOT=%~dp0.."

start "VehicleManagement FastAPI" cmd /k "cd /d ""%ROOT%\backend"" && if not exist .venv python -m venv .venv && call .venv\Scripts\activate && pip install -r requirements.txt && alembic upgrade head && python -m app.scripts.seed_vehicle_catalog && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
timeout /t 5 /nobreak >nul
start "VehicleManagement Next.js" cmd /k "cd /d ""%ROOT%\frontend"" && npm install && npm run dev"
start http://localhost:3000
