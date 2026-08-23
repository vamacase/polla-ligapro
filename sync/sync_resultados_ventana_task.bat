@echo off
REM Corre resultados-si-en-ventana: solo hace scraping real si hay un
REM partido en curso ahora mismo (ver hay_partido_en_ventana() en
REM sync_polla.py). Pensado para correr cada 15-20 min sin desperdiciar
REM recursos fuera de horario de partidos.
cd /d "%~dp0.."
echo ==== %date% %time% ==== >> sync\sync_resultados_log.txt
"C:\Users\vicen\AppData\Local\Programs\Python\Python314\python.exe" sync\sync_polla.py resultados-si-en-ventana --prod >> sync\sync_resultados_log.txt 2>&1
echo. >> sync\sync_resultados_log.txt
