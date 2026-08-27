@echo off
REM ==========================================================================
REM BridgeTalk - one-time setup (Windows)
REM
REM   scripts\setup.bat
REM
REM Creates the Python 3.11 virtual environment, installs pinned Python and npm
REM dependencies, downloads the MediaPipe HandLandmarker assets, and creates a
REM .env from the template if you do not have one yet.
REM
REM Safe to re-run: every step is idempotent.
REM ==========================================================================
setlocal enabledelayedexpansion

REM Resolve the repository root from this script's own location.
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.."
set "ROOT_DIR=%CD%"

echo.
echo ==^> Locating Python 3.11

REM The Windows Python launcher (py) is the reliable way to pick a version.
set "PYTHON_BIN="
py -3.11 --version >nul 2>&1 && set "PYTHON_BIN=py -3.11"
if not defined PYTHON_BIN (
  py -3.12 --version >nul 2>&1 && set "PYTHON_BIN=py -3.12"
)
if not defined PYTHON_BIN (
  echo   [X] Python 3.11 not found.
  echo       Install it from https://www.python.org/downloads/release/python-3119/
  echo       Tick "Add python.exe to PATH" during installation, then re-run this script.
  popd & exit /b 1
)
for /f "delims=" %%v in ('%PYTHON_BIN% --version 2^>^&1') do echo   [OK] Using %%v

echo.
echo ==^> Creating virtual environment (.venv)
if exist ".venv\Scripts\python.exe" (
  echo   [OK] .venv already exists - reusing it
) else (
  %PYTHON_BIN% -m venv .venv
  if errorlevel 1 ( echo   [X] Failed to create .venv & popd & exit /b 1 )
  echo   [OK] Created .venv
)

call .venv\Scripts\activate.bat

echo.
echo ==^> Installing Python dependencies (this takes a few minutes - TensorFlow is large)
python -m pip install --upgrade pip setuptools wheel >nul
python -m pip install -r backend\requirements.txt
if errorlevel 1 ( echo   [X] pip install failed & popd & exit /b 1 )
echo   [OK] Python dependencies installed

echo.
echo ==^> Checking Node.js
where node >nul 2>&1
if errorlevel 1 (
  echo   [X] Node.js not found. Install Node 20 LTS or newer from https://nodejs.org
  popd & exit /b 1
)
for /f "delims=" %%v in ('node --version') do echo   [OK] Node %%v

echo.
echo ==^> Installing npm dependencies
pushd frontend
call npm install
if errorlevel 1 ( echo   [X] npm install failed & popd & popd & exit /b 1 )
popd
echo   [OK] npm dependencies installed

echo.
echo ==^> Fetching MediaPipe HandLandmarker assets
set "MODEL_DIR=frontend\public\models"
set "MODEL_FILE=%MODEL_DIR%\hand_landmarker.task"
set "MODEL_URL=https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"

if exist "%MODEL_FILE%" (
  echo   [OK] hand_landmarker.task already present
) else (
  curl -fsSL --retry 3 -o "%MODEL_FILE%" "%MODEL_URL%"
  if errorlevel 1 (
    if exist "%MODEL_FILE%" del "%MODEL_FILE%"
    echo   [!] Could not download hand_landmarker.task ^(offline or blocked network^).
    echo   [!] Download it manually from:
    echo   [!]   %MODEL_URL%
    echo   [!] and save it to %MODEL_FILE%
  ) else (
    echo   [OK] Downloaded hand_landmarker.task
  )
)

REM The WASM runtime ships inside the npm package. Copying it into public\
REM means Vite serves it from our own origin, which avoids the "MediaPipe
REM WASM 404" failure on networks that block external CDNs.
set "WASM_SRC=frontend\node_modules\@mediapipe\tasks-vision\wasm"
set "WASM_DEST=%MODEL_DIR%\wasm"
if exist "%WASM_SRC%" (
  if not exist "%WASM_DEST%" mkdir "%WASM_DEST%"
  copy /Y "%WASM_SRC%\*" "%WASM_DEST%\" >nul
  echo   [OK] Copied MediaPipe WASM runtime to %WASM_DEST%
) else (
  echo   [!] MediaPipe WASM runtime not found at %WASM_SRC% - did npm install succeed?
)

echo.
echo ==^> Checking .env
if exist ".env" (
  echo   [OK] .env already exists - leaving it untouched
) else (
  copy /Y ".env.example" ".env" >nul
  echo   [!] Created .env from .env.example - you MUST edit it:
  echo   [!]   - DATABASE_URL   : your MySQL user and password
  echo   [!]   - JWT_SECRET_KEY : python -c "import secrets; print(secrets.token_urlsafe(48))"
)

echo.
echo ==^> Setup complete
echo.
echo Next steps:
echo   1. Edit .env (database URL + JWT secret).
echo   2. Create the database:   mysql -u root -p ^< database\schema.sql
echo   3. Start the backend:     scripts\run_backend.bat
echo   4. Start the frontend:    scripts\run_frontend.bat
echo   5. Open http://localhost:5173

popd
endlocal
