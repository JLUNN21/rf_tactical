@echo off
echo ========================================
echo RF Tactical - Launch Script
echo ========================================

REM Set paths
set RADIOCONDA_PATH=C:\Users\jakel\Desktop\radioconda
set PROJECT_PATH=%~dp0

echo.
echo [1/3] Setting up environment...

REM Add radioconda to PATH (bin, Library\bin, and Scripts)
set PATH=%RADIOCONDA_PATH%;%RADIOCONDA_PATH%\Library\bin;%RADIOCONDA_PATH%\Library\mingw-w64\bin;%RADIOCONDA_PATH%\Library\usr\bin;%RADIOCONDA_PATH%\Scripts;%PATH%

REM Set SoapySDR plugin path
set SOAPY_SDR_PLUGIN_PATH=%RADIOCONDA_PATH%\Library\lib\SoapySDR\modules0.8

REM Set Python path
set PYTHONPATH=%RADIOCONDA_PATH%\Lib\site-packages

echo       PATH configured
echo       SOAPY_SDR_PLUGIN_PATH: %SOAPY_SDR_PLUGIN_PATH%

echo.
echo [2/3] Checking environment...

if not exist "%RADIOCONDA_PATH%\python.exe" (
    echo ERROR: Python not found in radioconda
    pause
    exit /b 1
)

echo       Python: OK
echo       radioconda: OK

echo.
echo [3/3] Launching RF Tactical...
echo.

cd /d "%PROJECT_PATH%"
"%RADIOCONDA_PATH%\python.exe" main.py

if errorlevel 1 (
    echo.
    echo ERROR: Application crashed or exited with error
    pause
)
