@echo off
setlocal
cd /d "%~dp0"
if not exist "bootstrap.py" (
  echo Extract the ENTIRE ZIP first, then run this launcher from the extracted folder.
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" bootstrap.py --stop
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 bootstrap.py --stop
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python bootstrap.py --stop
  goto done
)
echo Python was not found. Install Python 3.10 or newer from python.org with the launcher enabled.
echo Then double-click Start PinSpector.cmd again. No administrator launch is needed.
pause
exit /b 1
:done
if errorlevel 1 (
  echo.
  echo Startup failed. The details above and data\logs\launcher.log identify the failure.
  pause
  exit /b 1
)
pause
