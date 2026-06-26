@echo off
setlocal

set "APP_DIR=%~dp0"
set "BUNDLED_PY=C:\Users\Mohamed nagy\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=%APP_DIR%stockflow_server_dashboard.py"

if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" "%SCRIPT%"
  goto :eof
)

where py >nul 2>nul
if %errorlevel%==0 (
  py "%SCRIPT%"
  goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
  python "%SCRIPT%"
  goto :eof
)

echo لم يتم العثور على بايثون لتشغيل البرنامج.
pause
