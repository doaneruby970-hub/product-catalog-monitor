@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "PROFILE_DIR=%PROJECT_DIR%browser-profile"
set "DEBUG_PORT=9223"
set "START_URL=https://www.amazon.com/"

set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_EXE%" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME_EXE%" (
    echo Chrome was not found. Install Google Chrome first.
    exit /b 1
)

if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

powershell -NoProfile -Command "try { $null = Invoke-RestMethod 'http://127.0.0.1:%DEBUG_PORT%/json/version' -TimeoutSec 2; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
    echo Persistent project Chrome is already running on port %DEBUG_PORT%.
    exit /b 0
)

start "Catalog Monitor Chrome" "%CHROME_EXE%" ^
  --remote-debugging-address=0.0.0.0 ^
  --remote-debugging-port=%DEBUG_PORT% ^
  --user-data-dir="%PROFILE_DIR%" ^
  --no-first-run ^
  --no-default-browser-check ^
  --start-maximized ^
  "%START_URL%"

echo Started persistent project Chrome.
echo Profile: %PROFILE_DIR%
echo CDP: http://127.0.0.1:%DEBUG_PORT%
endlocal
