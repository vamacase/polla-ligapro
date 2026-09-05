@echo off
REM Corre sync_polla.py recordatorio-faltantes --prod: envia el correo
REM "aun no has predicho" solo a jugadores con 0 predicciones en la fecha.
REM Programado via Task Scheduler al kickoff del primer partido de la fecha
REM (ver programar_recordatorio_faltantes).
cd /d "%~dp0.."
echo ==== %date% %time% ==== >> sync\sync_resultados_log.txt
"C:\Users\vicen\AppData\Local\Programs\Python\Python314\python.exe" sync\sync_polla.py recordatorio-faltantes --prod >> sync\sync_resultados_log.txt 2>&1
echo. >> sync\sync_resultados_log.txt
