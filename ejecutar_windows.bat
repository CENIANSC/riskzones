@echo off
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 (
    echo Error al instalar dependencias. Comprueba Python y la conexion.
    pause
    exit /b 1
)
py -3 -m streamlit run app.py
pause
