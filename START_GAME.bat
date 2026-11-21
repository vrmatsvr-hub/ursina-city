@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Ursina City - Launcher
cd /d "%~dp0"

echo ==============================================
echo   URSINA CITY - launcher
echo ==============================================
echo.

set "PY="

rem ---- 1. look for a compatible Python (3.9 - 3.13; Panda3D has no wheels for newer yet)
for %%V in (3.12 3.11 3.13 3.10 3.9) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    for %%P in (python python3) do (
        if not defined PY (
            %%P -c "import sys; exit(0 if (3,9) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && set "PY=%%P"
        )
    )
)
if not defined PY (
    for %%D in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python311" "%ProgramFiles%\Python312" "%ProgramFiles%\Python311") do (
        if not defined PY if exist "%%~D\python.exe" set "PY="%%~D\python.exe""
    )
)

rem ---- 2. no Python found -> install Python 3.12
if not defined PY (
    echo [!] No compatible Python found. Installing Python 3.12 ...
    echo.
    where winget >nul 2>&1
    if !errorlevel! == 0 (
        echo     Using winget ...
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    )
    if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        echo     Downloading the installer from python.org ...
        set "INST=%TEMP%\python-3.12.8-amd64.exe"
        curl -L -o "!INST!" https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe
        if not exist "!INST!" (
            powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile '!INST!'"
        )
        if not exist "!INST!" (
            echo [X] Could not download Python. Install it manually from https://www.python.org/downloads/
            pause
            exit /b 1
        )
        echo     Running the installer ^(this can take a minute^) ...
        "!INST!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1
    )
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
    ) else (
        echo [X] Python installation failed. Install Python 3.12 from https://www.python.org/downloads/
        echo     and tick "Add python.exe to PATH", then run this file again.
        pause
        exit /b 1
    )
)

echo [OK] Using Python:
%PY% --version
echo.

rem ---- 3. make sure pip and the libraries are installed
%PY% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [..] Installing pip ...
    %PY% -m ensurepip --upgrade
)

%PY% -c "import ursina, numpy" >nul 2>&1
if errorlevel 1 (
    echo [..] Installing game libraries: ursina, numpy ...
    %PY% -m pip install --upgrade pip
    %PY% -m pip install --upgrade ursina numpy
    %PY% -c "import ursina, numpy" >nul 2>&1
    if errorlevel 1 (
        echo [X] Library installation failed. See the messages above.
        pause
        exit /b 1
    )
)
echo [OK] Libraries ready.
echo.

rem ---- 4. check GitHub for a newer version (savegame.json is never touched)
echo [..] Checking for updates ...
%PY% updater.py
echo.

rem ---- 5. start the game
echo Starting Ursina City ...
echo.
%PY% main.py --no-update
if errorlevel 1 (
    echo.
    echo [X] The game stopped with an error. Copy the text above and send it so it can be fixed.
    pause
    exit /b 1
)
endlocal
