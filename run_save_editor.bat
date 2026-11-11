@echo off
setlocal EnableDelayedExpansion

:: -----------------------------------------------------------------
:: Touchgrind Skate 2 // Save Editor Launcher for Windows
:: -----------------------------------------------------------------

:: Switch to repository root directory
cd /d "%~dp0"

echo ====================================================
echo TOUCHGRIND SKATE 2 // SAVE EDITOR
echo ====================================================
echo.

:: Detect Python interpreter: try 'python', then fallback to 'py -3'
set "PY_CMD="

python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PY_CMD=python"
    goto :found_python
)

py -3 --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PY_CMD=py -3"
    goto :found_python
)

:: Python missing: display clear guidance and halt
echo [ERROR] Python 3 was not detected on your system PATH.
echo.
echo Touchgrind Skate 2 Save Editor requires Python 3.10 or newer.
echo.
echo Please follow these steps to install Python:
echo   1. Download Python from: https://www.python.org/downloads/
echo   2. Run the installer and CRITICALLY check the box:
echo      "[X] Add python.exe to PATH"
echo   3. Finish installation and re-launch this script.
echo.
echo ====================================================
pause
exit /b 1

:found_python
echo [INFO] Detected Python runtime:
%PY_CMD% --version
echo.

:: Port configuration (default 8765, allows CLI override: run_save_editor.bat 9000)
set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"

set "URL=http://localhost:%PORT%"
echo [INFO] Starting web server on %URL% ...
echo [INFO] Launching default web browser...
echo.

:: Launch browser in parallel
if "%PORT%"=="8765" (
    start http://localhost:8765
) else (
    start http://localhost:%PORT%
)

:: Launch Python server module (logs to console, blocks until Ctrl+C)
%PY_CMD% -m editor.server --port %PORT%

echo.
echo ====================================================
echo [INFO] Save Editor server has stopped.
echo ====================================================
pause
