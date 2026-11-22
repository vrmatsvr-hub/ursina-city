@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Ursina City - Updater
cd /d "%~dp0"
echo ==============================================
echo   URSINA CITY - update check
echo ==============================================
echo.

set "PY="
for %%V in (3.12 3.11 3.13 3.10 3.9) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    for %%P in (python python3) do (
        if not defined PY (
            %%P -c "import sys" >nul 2>&1 && set "PY=%%P"
        )
    )
)
if not defined PY (
    for %%D in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python311") do (
        if not defined PY if exist "%%~D\python.exe" set "PY="%%~D\python.exe""
    )
)
if not defined PY (
    echo [X] Python was not found. Run START_GAME.bat once first - it installs everything.
    pause
    exit /b 1
)
if not exist "updater.py" (
    echo [X] updater.py is missing from this folder.
    pause
    exit /b 1
)

%PY% updater.py
set "RC=%errorlevel%"
echo.
if "%RC%"=="10" (
    echo [OK] Ursina City was updated. Your savegame was kept.
) else if "%RC%"=="0" (
    echo [OK] You already have the newest version.
) else (
    echo [!] Could not update right now ^(no internet or GitHub unreachable^). Your game was not changed.
)
echo.
choice /C YN /M "Start the game now"
if errorlevel 2 exit /b 0
start "" cmd /c "%~dp0START_GAME.bat"
endlocal
