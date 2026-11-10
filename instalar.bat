@echo off
rem Descomprime turnos_simple.zip (debe estar en esta misma carpeta) y corre el programa.
cd /d "%~dp0"
if not exist turnos_simple.zip (
  echo No encuentro turnos_simple.zip en esta carpeta.
  pause
  exit /b 1
)
powershell -NoProfile -Command "Expand-Archive -Path 'turnos_simple.zip' -DestinationPath '.' -Force"
cd turnos_simple
call iniciar.bat
