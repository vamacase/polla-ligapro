@echo off
REM Corre sync_polla.py resultados --prod y registra la salida con fecha.
REM Programado via Task Scheduler porque GitHub Actions (IP de datacenter)
REM es bloqueado con más frecuencia por Cloudflare en SofaScore que esta PC.
cd /d "%~dp0.."
echo ==== %date% %time% ==== >> sync\sync_resultados_log.txt
"C:\Users\vicen\AppData\Local\Programs\Python\Python314\python.exe" sync\sync_polla.py resultados --prod >> sync\sync_resultados_log.txt 2>&1
echo. >> sync\sync_resultados_log.txt
