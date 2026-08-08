@echo off
setlocal
REM Derive repo root from this script (scripts\ -> parent). Use subst to avoid & in path for npm/vite.
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT=%%~fI"
if not exist "%ROOT%\pyproject.toml" (
  echo [ERROR] pyproject.toml not found at "%ROOT%"
  exit /b 1
)
subst V: "%ROOT%" 2>nul
cd /d V:\apps\desktop
call npm run build
set "EXITCODE=%ERRORLEVEL%"
exit /b %EXITCODE%
