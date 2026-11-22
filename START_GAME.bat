@echo off
setlocal EnableExtensions EnableDelayedExpansion
title URSINA CITY - Launcher
chcp 65001 >nul
cd /d "%~dp0"
set "ESC="
set "R=%ESC%[0m"
set "OK=%ESC%[38;2;90;230;120m"
set "WAIT=%ESC%[38;2;255;200;80m"
set "BAD=%ESC%[38;2;255;70;70m"
set "DIM=%ESC%[38;2;150;150;160m"
set "RED=%ESC%[38;2;220;30;40m"
cls
echo.
echo([38;2;150;0;10m  ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════[0m
echo(  [38;2;255;140;130m████            ████████    ████    ████  ████    ████    ██████████  ████    ████  ████████████  ██████████[0m
echo(  [38;2;244;58;50m████[38;2;120;0;8m▓▓        [38;2;244;58;50m████[38;2;120;0;8m▓▓▓▓[38;2;244;58;50m████  ████[38;2;120;0;8m▓▓  [38;2;244;58;50m████[38;2;120;0;8m▓▓[38;2;244;58;50m██████  ████[38;2;120;0;8m▓▓[38;2;244;58;50m████[38;2;120;0;8m▓▓▓▓▓▓▓▓▓▓[38;2;244;58;50m████[38;2;120;0;8m▓▓  [38;2;244;58;50m████[38;2;120;0;8m▓▓[38;2;244;58;50m████[38;2;120;0;8m▓▓▓▓▓▓▓▓▓▓[38;2;244;58;50m████[38;2;120;0;8m▓▓▓▓[38;2;244;58;50m████[0m
echo(  [38;2;232;46;40m████[38;2;114;0;8m▓▓        [38;2;232;46;40m████[38;2;114;0;8m▓▓  [38;2;232;46;40m████[38;2;114;0;8m▓▓[38;2;232;46;40m████[38;2;114;0;8m▓▓  [38;2;232;46;40m████[38;2;114;0;8m▓▓[38;2;232;46;40m████████████[38;2;114;0;8m▓▓[38;2;232;46;40m████[38;2;114;0;8m▓▓        [38;2;232;46;40m████[38;2;114;0;8m▓▓  [38;2;232;46;40m████[38;2;114;0;8m▓▓[38;2;232;46;40m████[38;2;114;0;8m▓▓        [38;2;232;46;40m████[38;2;114;0;8m▓▓  [38;2;232;46;40m████[38;2;114;0;8m▓▓[0m
echo(  [38;2;220;35;30m████[38;2;108;0;8m▓▓        [38;2;220;35;30m████████████[38;2;108;0;8m▓▓[38;2;220;35;30m████[38;2;108;0;8m▓▓  [38;2;220;35;30m████[38;2;108;0;8m▓▓[38;2;220;35;30m████[38;2;108;0;8m▓▓[38;2;220;35;30m██████[38;2;108;0;8m▓▓[38;2;220;35;30m████[38;2;108;0;8m▓▓        [38;2;220;35;30m████████████[38;2;108;0;8m▓▓[38;2;220;35;30m██████████    ██████████[38;2;108;0;8m▓▓▓▓[0m
echo(  [38;2;209;23;20m████[38;2;102;0;8m▓▓        [38;2;209;23;20m████[38;2;102;0;8m▓▓▓▓[38;2;209;23;20m████[38;2;102;0;8m▓▓[38;2;209;23;20m████[38;2;102;0;8m▓▓  [38;2;209;23;20m████[38;2;102;0;8m▓▓[38;2;209;23;20m████[38;2;102;0;8m▓▓  [38;2;209;23;20m████[38;2;102;0;8m▓▓[38;2;209;23;20m████[38;2;102;0;8m▓▓        [38;2;209;23;20m████[38;2;102;0;8m▓▓▓▓[38;2;209;23;20m████[38;2;102;0;8m▓▓[38;2;209;23;20m████[38;2;102;0;8m▓▓▓▓▓▓▓▓  [38;2;209;23;20m████[38;2;102;0;8m▓▓[38;2;209;23;20m████[38;2;102;0;8m▓▓[0m
echo(  [38;2;197;11;9m████[38;2;96;0;8m▓▓        [38;2;197;11;9m████[38;2;96;0;8m▓▓  [38;2;197;11;9m████[38;2;96;0;8m▓▓[38;2;197;11;9m████[38;2;96;0;8m▓▓  [38;2;197;11;9m████[38;2;96;0;8m▓▓[38;2;197;11;9m████[38;2;96;0;8m▓▓  [38;2;197;11;9m████[38;2;96;0;8m▓▓[38;2;197;11;9m████[38;2;96;0;8m▓▓        [38;2;197;11;9m████[38;2;96;0;8m▓▓  [38;2;197;11;9m████[38;2;96;0;8m▓▓[38;2;197;11;9m████[38;2;96;0;8m▓▓        [38;2;197;11;9m████[38;2;96;0;8m▓▓  [38;2;197;11;9m████[0m
echo(  [38;2;185;0;0m████████████  ████[38;2;90;0;8m▓▓  [38;2;185;0;0m████[38;2;90;0;8m▓▓  [38;2;185;0;0m████████[38;2;90;0;8m▓▓▓▓[38;2;185;0;0m████[38;2;90;0;8m▓▓  [38;2;185;0;0m████[38;2;90;0;8m▓▓  [38;2;185;0;0m██████████  ████[38;2;90;0;8m▓▓  [38;2;185;0;0m████[38;2;90;0;8m▓▓[38;2;185;0;0m████████████  ████[38;2;90;0;8m▓▓  [38;2;185;0;0m████[38;2;90;0;8m▓▓[0m
echo(    [38;2;84;0;8m▓▓▓▓▓▓▓▓▓▓▓▓  ▓▓▓▓    ▓▓▓▓    ▓▓▓▓▓▓▓▓    ▓▓▓▓    ▓▓▓▓    ▓▓▓▓▓▓▓▓▓▓  ▓▓▓▓    ▓▓▓▓  ▓▓▓▓▓▓▓▓▓▓▓▓  ▓▓▓▓    ▓▓▓▓[0m
echo(    [38;2;183;6;11m██      [38;2;179;6;11m██[38;2;140;4;7m▓▓    [38;2;161;5;9m██    [38;2;140;4;7m▐▌          [38;2;172;6;10m██[38;2;183;6;11m██                    [38;2;179;6;11m██  [38;2;183;6;11m██  [38;2;172;6;10m██    [38;2;140;4;7m▒▒    [38;2;161;5;9m████  [38;2;179;6;11m████    [38;2;183;6;11m██    [38;2;140;4;7m▐▌[0m
echo(    [38;2;161;5;9m██      [38;2;153;4;8m██      [38;2;118;2;4m░░                [38;2;140;4;7m██[38;2;161;5;9m██                    [38;2;153;4;8m██  [38;2;161;5;9m██  [38;2;140;4;7m██          [38;2;118;2;4m▓▓▒▒  [38;2;153;4;8m████    [38;2;161;5;9m██[0m
echo(    [38;2;140;4;7m██      [38;2;127;3;5m██                        [38;2;107;2;3m ▼[38;2;140;4;7m██                    [38;2;127;3;5m██  [38;2;140;4;7m██  [38;2;107;2;3m▒▒                [38;2;127;3;5m████    [38;2;140;4;7m██[0m
echo(    [38;2;118;2;4m██      [38;2;101;1;2m▒▒                          [38;2;118;2;4m██                    [38;2;101;1;2m▒▒  [38;2;118;2;4m██                    [38;2;101;1;2m▒▒▒▒    [38;2;118;2;4m██[0m
echo(    [38;2;96;1;2m▒▒                                  ▒▒                        ▒▒                            ▒▒[0m
echo(                                                                            [38;2;38;26;40m████████████████  █████[0m
echo(                 [38;2;38;26;40m██████                            ██████          ████████ [38;2;255;200;80m▪[38;2;38;26;40m█[38;2;255;200;80m▪[38;2;38;26;40m████████[38;2;255;200;80m▪[38;2;38;26;40m███[38;2;255;200;80m▪  [38;2;38;26;40m█████[0m
echo(          [38;2;38;26;40m███████[38;2;255;200;80m▪[38;2;38;26;40m█[38;2;255;200;80m▪[38;2;38;26;40m████████         █████         ██████     █████████████ ██████████████[38;2;255;200;80m▪[38;2;38;26;40m█  ███[38;2;255;200;80m▪[38;2;38;26;40m██████████ █████[0m
echo(  [38;2;38;26;40m███████ ███████████████[38;2;255;200;80m▪[38;2;38;26;40m██ ████████████[38;2;255;200;80m▪ [38;2;38;26;40m██████  ██[38;2;255;200;80m▪[38;2;38;26;40m█[38;2;255;200;80m▪[38;2;38;26;40m█ █████[38;2;255;200;80m▪[38;2;38;26;40m█[38;2;255;200;80m▪[38;2;38;26;40m████████[38;2;255;200;80m▪ [38;2;38;26;40m████████████████  █[38;2;255;200;80m▪[38;2;38;26;40m███[38;2;255;200;80m▪[38;2;38;26;40m███[38;2;255;200;80m▪[38;2;38;26;40m██[38;2;255;200;80m▪[38;2;38;26;40m█ ███[38;2;255;200;80m▪[38;2;38;26;40m█[0m
echo(  [38;2;90;90;96m▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀[0m
echo(  [38;2;255;120;40m  U R S I N A   C I T Y[38;2;150;150;160m   ::   open world crime  +  drifting  +  e-mobility  +  fireworks[0m
echo([38;2;150;0;10m  ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════[0m
echo.
set "VER=?"
for /f "tokens=2 delims=:, " %%v in ('findstr /c:"\"version\"" version.json 2^>nul') do set "VER=%%~v"
echo   %DIM%version %R%%WAIT%!VER!%R%   %DIM%^|  github.com/vrmatsvr-hub/ursina-city%R%
echo.

call :progress 0 "Looking for Python"
set "PY="
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

if not defined PY (
    echo   %WAIT%[ .. ]%R% No compatible Python found - installing Python 3.12 ...
    where winget >nul 2>&1
    if !errorlevel! == 0 (
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    )
    if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        echo   %WAIT%[ .. ]%R% Downloading the installer from python.org ...
        set "INST=%TEMP%\python-3.12.8-amd64.exe"
        curl -L -o "!INST!" https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe
        if not exist "!INST!" (
            powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile '!INST!'"
        )
        if not exist "!INST!" (
            echo   %BAD%[FAIL]%R% Could not download Python. Install it from https://www.python.org/downloads/
            pause
            exit /b 1
        )
        echo   %WAIT%[ .. ]%R% Running the Python installer ^(this can take a minute^) ...
        "!INST!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1
    )
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
    ) else (
        echo   %BAD%[FAIL]%R% Python installation failed. Install Python 3.12 from https://www.python.org/downloads/
        echo          and tick "Add python.exe to PATH", then run this file again.
        pause
        exit /b 1
    )
)
for /f "delims=" %%i in ('%PY% --version 2^>^&1') do set "PYVER=%%i"
echo   %OK%[ OK ]%R% !PYVER!

call :progress 1 "Checking game libraries"
%PY% -m pip --version >nul 2>&1
if errorlevel 1 %PY% -m ensurepip --upgrade >nul 2>&1
%PY% -c "import ursina, numpy" >nul 2>&1
if errorlevel 1 (
    echo   %WAIT%[ .. ]%R% Installing ursina + numpy ^(first time only^) ...
    %PY% -m pip install --upgrade pip
    %PY% -m pip install --upgrade ursina numpy
    %PY% -c "import ursina, numpy" >nul 2>&1
    if errorlevel 1 (
        echo   %BAD%[FAIL]%R% Library installation failed. See the messages above.
        pause
        exit /b 1
    )
)
echo   %OK%[ OK ]%R% ursina + numpy ready

call :progress 2 "Checking GitHub for updates"
%PY% updater.py >nul 2>&1
set "UPRC=!errorlevel!"
if "!UPRC!"=="10" (
    echo   %OK%[ OK ]%R% Updated to the newest version %DIM%^(savegame kept^)%R%
) else if "!UPRC!"=="0" (
    echo   %OK%[ OK ]%R% You have the newest version
) else (
    echo   %WAIT%[ !! ]%R% Could not check for updates - starting anyway
)

call :progress 3 "Starting Ursina City"
echo.
echo   %RED%  Drive fast. Drift harder. Don't get BUSTED.%R%
echo.
%PY% main.py --no-update
if errorlevel 1 (
    echo.
    echo   %BAD%[FAIL]%R% The game stopped with an error. Copy the text above and send it so it can be fixed.
    pause
    exit /b 1
)
endlocal
exit /b 0

:progress
rem  %1 = step 0..3, %2 = label   -> draws a red progress bar
set /a "FILL=(%~1+1)*8"
set "BARTXT="
for /l %%i in (1,1,32) do (
    if %%i leq !FILL! (set "BARTXT=!BARTXT!█") else (set "BARTXT=!BARTXT!░")
)
set /a "PCT=(%~1+1)*25"
echo.
echo   %RED%!BARTXT!%R% %WAIT%!PCT!%%%R%  %DIM%%~2 ...%R%
exit /b 0
