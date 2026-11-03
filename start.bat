@echo off
rem Einmalige Einrichtung bzw. Reparatur. Danach einfach die Verknuepfung "ModNest" benutzen (ohne Konsolenfenster).
cd /d "%~dp0"
.venv\Scripts\python.exe -c "import PySide6, minecraft_launcher_lib, requests" >nul 2>&1
if errorlevel 1 (
    echo Richte ModNest ein, einen Moment ...
    if exist .venv rmdir /s /q .venv
    python -m venv .venv || (echo Python wurde nicht gefunden. & pause & exit /b 1)
    .venv\Scripts\python -m pip install -q -r requirements.txt || (pause & exit /b 1)
)
if not exist ModNest.lnk .venv\Scripts\python.exe main.py --create-shortcuts
start "" .venv\Scripts\pythonw.exe main.py
