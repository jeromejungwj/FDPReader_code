@echo off
rem Same as run.bat but keeps a console window open so error messages are visible.
setlocal
if not exist "%~dp0.venv\.installed" (
    echo [FDP Reader] Run run.bat once first to install the packages.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0FDPReader.pyw" %*
pause
