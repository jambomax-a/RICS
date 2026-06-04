@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   RICS (Reference Integrity Check System)
echo ==========================================
echo.

echo Starting RICS Server...
echo Portal: http://localhost:8000
echo.

:: Run the server via PowerShell script
powershell.exe -ExecutionPolicy RemoteSigned -File ".\run.ps1" -Port 8000

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Server stopped with error code %ERRORLEVEL%.
    pause
)

endlocal
