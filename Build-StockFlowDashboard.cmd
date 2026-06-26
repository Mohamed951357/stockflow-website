@echo off
setlocal

set "APP_DIR=%~dp0"
set "BUNDLED_PY=C:\Users\Mohamed nagy\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "SCRIPT=%APP_DIR%stockflow_server_dashboard.py"

if not exist "%BUNDLED_PY%" (
  echo لم يتم العثور على مفسر بايثون المرفق.
  pause
  exit /b 1
)

"%BUNDLED_PY%" -m PyInstaller --noconfirm --onefile --windowed --name StockFlowServerDashboard "%SCRIPT%"

if %errorlevel% neq 0 (
  echo فشل البناء. تأكد أن PyInstaller مثبت اولاً.
  pause
  exit /b 1
)

echo تم البناء. ستجد الملف التنفيذي داخل مجلد dist
pause
