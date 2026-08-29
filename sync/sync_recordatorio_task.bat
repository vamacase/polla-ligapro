@echo off
REM Corre sync_polla.py recordatorio-60min --prod: envia el correo de "faltan
REM 60 minutos" a los 10 jugadores. Programado via Task Scheduler a
REM primer_kickoff_de_la_fecha - 60 min (ver programar_recordatorio_60min).
cd /d "%~dp0.."
echo ==== %date% %time% ==== >> sync\sync_resultados_log.txt
"C:\Users\vicen\AppData\Local\Programs\Python\Python314\python.exe" sync\sync_polla.py recordatorio-60min --prod >> sync\sync_resultados_log.txt 2>&1
echo. >> sync\sync_resultados_log.txt
