@echo off
setlocal
chcp 65001 >nul
title Phoenix Aero Lite
set "PAL_ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PAL_ROOT%scripts\start_phoenix_aero_lite.ps1" %*
set "PAL_EXIT_CODE=%ERRORLEVEL%"
if not "%PAL_EXIT_CODE%"=="0" (
  echo.
  echo Phoenix Aero Lite 未能启动，请保留上面的中文诊断。
  pause
)
endlocal & exit /b %PAL_EXIT_CODE%
