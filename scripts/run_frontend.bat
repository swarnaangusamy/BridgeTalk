@echo off
REM ==========================================================================
REM BridgeTalk - start the React frontend (Windows)
REM
REM   scripts\run_frontend.bat
REM
REM Vite dev server on http://localhost:5173.
REM
REM Camera note: browsers only grant getUserMedia on a secure context, which
REM means HTTPS or localhost. http://localhost:5173 works. Reaching this
REM machine from a second laptop over http://192.168.x.x will NOT get camera
REM access - see the two-machine testing section of the README.
REM ==========================================================================
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\frontend"

if not exist "node_modules" (
  echo [X] No node_modules found. Run scripts\setup.bat first.
  popd & exit /b 1
)

echo Starting BridgeTalk frontend on http://localhost:5173
call npm run dev

popd
endlocal
