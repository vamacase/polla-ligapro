@echo off
REM Doble clic para actualizar resultados de la Polla en PRODUCCION al momento.
REM Corre sync_polla.py resultados --prod y muestra el progreso en pantalla.
REM El log compartido (sync_resultados_log.txt) vive en Google Drive y puede
REM quedar bloqueado unos segundos mientras Drive sincroniza -- por eso el
REM registro al log se hace aparte, con reintentos, sin frenar la corrida
REM principal que ya viste en pantalla.
setlocal
set PY="C:\Users\vicen\AppData\Local\Programs\Python\Python314\python.exe"
cd /d "%~dp0.."

%PY% sync\sync_polla.py resultados --prod

echo.
echo ==== Listo. Registrando en el log... ====

for /L %%i in (1,1,5) do (
    (echo ==== %date% %time% (manual) ==== >> sync\sync_resultados_log.txt) 2>nul && goto :logged
    ping -n 3 127.0.0.1 >nul
)
:logged

echo ==== Listo. Presiona una tecla para cerrar ====
pause >nul
