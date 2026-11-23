@echo off
rem FDP Reader launcher. First run creates .venv and installs the packages.
rem No "cd": relative file arguments must resolve against the caller's folder.
setlocal
set "HOME_DIR=%~dp0"
set "PY=%HOME_DIR%.venv\Scripts\python.exe"

if exist "%HOME_DIR%.venv\.installed" goto launch

echo [FDP Reader] First run: creating .venv and installing packages. This can take a few minutes.
if exist "%PY%" goto install
where py >nul 2>nul
if errorlevel 1 (python -m venv "%HOME_DIR%.venv") else (py -3 -m venv "%HOME_DIR%.venv")
if not exist "%PY%" goto novenv

:install
"%PY%" -m pip install -r "%HOME_DIR%requirements.txt"
if errorlevel 1 goto failed
"%PY%" -m compileall -q "%HOME_DIR%app" "%HOME_DIR%core" "%HOME_DIR%features" "%HOME_DIR%storage"
echo ok> "%HOME_DIR%.venv\.installed"

:launch
start "" "%HOME_DIR%.venv\Scripts\pythonw.exe" "%HOME_DIR%FDPReader.pyw" %*
exit /b 0

:novenv
echo [FDP Reader] Could not create the virtual environment. Install Python 3.10 or newer.
pause
exit /b 1

:failed
echo [FDP Reader] Package installation failed. Check the messages above.
pause
exit /b 1
