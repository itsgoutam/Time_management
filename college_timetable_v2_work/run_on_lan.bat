
echo off
REM ====================================================
REM  GTM SmartSchedule — Run on Local LAN Network
REM ====================================================

title GTM SmartSchedule - LAN Server

echo.
echo ====================================================
echo   GTM SmartSchedule - LAN Network Server
echo ====================================================
echo.

REM Get the local IP address
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R "IPv4 Address"') do (
    set IP=%%A
    goto :got_ip
)

:got_ip
REM Remove leading spaces from IP
setlocal enabledelayedexpansion
set IP=!IP:~1!

echo   Starting server on all network interfaces...
echo.
echo   ACCESS FROM THIS COMPUTER:
echo   http://127.0.0.1:8000
echo.
echo   ACCESS FROM OTHER COMPUTERS ON YOUR LAN:
echo   http://!IP!:8000
echo.
echo ====================================================
echo.
echo   To access from other devices:
echo   1. Ensure they are on the same network
echo   2. Use the IP address above in a browser
echo   3. Press Ctrl+C to stop the server
echo.
echo ====================================================
echo.

REM Run the Django development server on all interfaces
python manage.py runserver 0.0.0.0:8000

REM If the server exits, pause to show any error messages
pause
