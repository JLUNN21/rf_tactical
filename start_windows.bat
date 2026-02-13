@echo off
REM RF Tactical Monitor - Windows Launcher
REM Activates radioconda environment for SoapySDR + HackRF support,
REM optionally starts dump1090 for ADS-B, then launches the main app.
REM
REM Prerequisites:
REM   - radioconda installed (winget install ryanvolz.radioconda)
REM   - HackRF One connected via USB (Zadig driver: WinUSB)

echo ============================================================
echo  RF TACTICAL MONITOR - Windows Launcher
echo ============================================================
echo.

REM ── Find radioconda ───────────────────────────────────────────
set RADIOCONDA=
if exist "%USERPROFILE%\radioconda\python.exe" (
    set "RADIOCONDA=%USERPROFILE%\radioconda"
) else if exist "%LOCALAPPDATA%\radioconda\python.exe" (
    set "RADIOCONDA=%LOCALAPPDATA%\radioconda"
) else if exist "C:\ProgramData\radioconda\python.exe" (
    set "RADIOCONDA=C:\ProgramData\radioconda"
) else if exist "C:\radioconda\python.exe" (
    set "RADIOCONDA=C:\radioconda"
)

if not defined RADIOCONDA (
    echo ERROR: radioconda not found!
    echo.
    echo Install radioconda:
    echo   winget install ryanvolz.radioconda
    echo.
    echo Then re-run this script.
    pause
    exit /b 1
)

echo Found radioconda at: %RADIOCONDA%

REM ── Activate radioconda environment ───────────────────────────
REM Add radioconda paths to PATH for DLL loading (hackrf-0.dll, libusb, etc.)
set "PATH=%RADIOCONDA%\Library\bin;%RADIOCONDA%;%RADIOCONDA%\Scripts;%PATH%"
set "SOAPY_SDR_PLUGIN_PATH=%RADIOCONDA%\Library\lib\SoapySDR\modules0.8"
set "PYTHONPATH="
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo Activated radioconda environment
"%RADIOCONDA%\python.exe" --version

REM ── Verify HackRF ────────────────────────────────────────────
echo.
echo Checking for HackRF...
"%RADIOCONDA%\python.exe" -c "import SoapySDR; r=SoapySDR.Device.enumerate('driver=hackrf'); print('HackRF devices found:', len(r)); [print('  Serial:', dict(x).get('serial','?')) for x in r]" 2>nul
echo.

REM ── Check for dump1090 ────────────────────────────────────────
set DUMP1090=
if exist "%~dp0tools\dump1090.exe" (
    set "DUMP1090=%~dp0tools\dump1090.exe"
    echo Found dump1090 in tools\ folder
) else (
    for /f "delims=" %%i in ('where dump1090.exe 2^>nul') do (
        if not defined DUMP1090 set "DUMP1090=%%i"
    )
    if defined DUMP1090 (
        echo Found dump1090 in PATH: %DUMP1090%
    )
)

REM ── Start dump1090 if found ───────────────────────────────────
if defined DUMP1090 (
    echo Starting dump1090 for ADS-B on port 30003/30005...
    start "dump1090" /MIN "%DUMP1090%" --net --device-type hackrf --quiet
    echo Waiting for dump1090 to initialize...
    timeout /t 3 /nobreak >nul
    echo dump1090 started - Beast on :30005, SBS on :30003
) else (
    echo NOTE: dump1090 not found - ADS-B will try network mode on localhost.
)

echo.
echo ============================================================
echo  Running Pre-Flight Check...
echo ============================================================
echo.

cd /d "%~dp0"
"%RADIOCONDA%\python.exe" preflight.py --full
set PREFLIGHT_RESULT=%ERRORLEVEL%
if %PREFLIGHT_RESULT% EQU 1 (
    echo.
    echo ============================================================
    echo  PRE-FLIGHT FAILED - Fix critical issues above before launching
    echo ============================================================
    pause
    exit /b 1
)
if %PREFLIGHT_RESULT% EQU 2 (
    echo.
    echo  Warnings detected but app can still run. Continuing...
    echo.
)

echo.
echo ============================================================
echo  Starting RF Tactical Monitor...
echo ============================================================
echo.

REM ── Launch the main application using radioconda Python ───────
"%RADIOCONDA%\python.exe" main.py

REM ── Cleanup on exit ───────────────────────────────────────────
if defined DUMP1090 (
    echo.
    echo Stopping dump1090...
    taskkill /FI "WINDOWTITLE eq dump1090" /F >nul 2>&1
    taskkill /IM dump1090.exe /F >nul 2>&1
)

echo.
echo RF Tactical Monitor closed.
pause
