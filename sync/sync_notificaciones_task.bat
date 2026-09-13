@echo off
REM Procesa la cola de correos de PRODUCCION. Esta tarea debe ejecutarse cada 15 min.
cd /d "%~dp0.."
echo ==== %date% %time% ==== >> sync\sync_notificaciones_log.txt
"C:\Users\vicen\AppData\Local\Programs\Python\Python314\python.exe" sync\sync_polla.py notificaciones --prod >> sync\sync_notificaciones_log.txt 2>&1
echo. >> sync\sync_notificaciones_log.txt
