@echo off
REM ============================================================
REM  Generador Automatico de Horarios Academicos
REM  Inicia el servidor web local en http://127.0.0.1:5000
REM ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro Python. Instalelo desde https://www.python.org
    pause
    exit /b 1
)

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"

if exist "%PY%" goto checkdeps

echo Creando entorno virtual...
python -m venv "%VENV%"
"%PY%" -m pip install --upgrade pip >nul

:checkdeps
"%PY%" -c "import flask, openpyxl, fpdf" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias...
    "%PY%" -m pip install -r requirements.txt
)

echo.
echo Iniciando el generador de horarios...
echo Abra http://127.0.0.1:5000 en su navegador.
echo Presione CTRL+C para detener el servidor.
echo.

start "" cmd /c "ping -n 3 127.0.0.1 >nul & start http://127.0.0.1:5000"
"%PY%" app.py
pause
