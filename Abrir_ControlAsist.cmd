@echo off
setlocal
cd /d "%~dp0"

REM Pythonw ejecuta el mismo app.py sin consola.
REM Por conservar esta carpeta como directorio actual, carga .env,
REM se conecta a Supabase y envía códigos Gmail igual que python.exe.
set "PYTHONW=.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=C:\Python310\pythonw.exe"

if not exist "%PYTHONW%" (
  echo No se encontro pythonw.exe.
  echo Instala Python o crea el entorno virtual indicado en README.md.
  pause
  exit /b 1
)

start "" "%PYTHONW%" app.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:5000

endlocal
exit /b
