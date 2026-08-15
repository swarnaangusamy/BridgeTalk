@echo off
REM ==========================================================================
REM BridgeTalk - start the FastAPI backend (Windows)
REM
REM   scripts\run_backend.bat
REM
REM Serves the REST API and both WebSocket endpoints on http://localhost:8000.
REM Interactive API docs: http://localhost:8000/docs
REM ==========================================================================
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."

if not exist ".venv\Scripts\activate.bat" (
  echo [X] No .venv found. Run scripts\setup.bat first.
  popd & exit /b 1
)
call .venv\Scripts\activate.bat

if not exist ".env" (
  echo [X] No .env found. Copy .env.example to .env and fill it in.
  popd & exit /b 1
)

REM Read BACKEND_HOST / BACKEND_PORT out of .env, falling back to defaults.
set "HOST=0.0.0.0"
set "PORT=8000"
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
  if "%%a"=="BACKEND_HOST" set "HOST=%%b"
  if "%%a"=="BACKEND_PORT" set "PORT=%%b"
)

echo Starting BridgeTalk API on http://localhost:%PORT%  (docs at /docs)

REM --app-dir backend puts backend\ on the import path, so `app.main` resolves.
uvicorn app.main:app --app-dir backend --host %HOST% --port %PORT% --reload

popd
endlocal
