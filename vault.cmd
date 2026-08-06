@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\vault.exe" (
    echo [Vault] Not installed yet. Run setup.ps1 first:
    echo   powershell -ExecutionPolicy Bypass -File setup.ps1
    exit /b 1
)

".venv\Scripts\vault.exe" %*
