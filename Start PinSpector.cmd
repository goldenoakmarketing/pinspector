@echo off
setlocal
cd /d "%~dp0"
if not exist "bootstrap.py" (
  echo Extract the ENTIRE ZIP first, then run this launcher from the extracted folder.
  pause
  exit /b 1
)
if exist "Start Local Model.ps1" (
  echo Starting the existing local Qwen service...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start Local Model.ps1"
  if errorlevel 1 (
    echo.
    echo The local AI service could not start. The dashboard was not opened.
    echo Check the error above and data\logs\model.stderr.log, then try again.
    pause
    exit /b 1
  )
) else if exist "Detect Local Model.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Detect Local Model.ps1"
  if errorlevel 1 echo Local model detection failed. Connect your runtime in Settings.
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" bootstrap.py 
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 bootstrap.py 
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python bootstrap.py 
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

