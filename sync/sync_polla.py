"""
SYNC POLLA — corre en tu PC (necesita Playwright para pasar Cloudflare de SofaScore).

Uso:
    python sync_polla.py fixture [ronda] [--prod]   # sube próximos partidos (predecibles)
    python sync_polla.py resultados [--prod]        # actualiza marcadores reales + cierra partidos
    python sync_polla.py resultados-si-en-ventana [--prod]  # como arriba, pero solo si hay
                                                      # un partido en curso (uso: tarea cada 15-20 min)
    python sync_polla.py programar-disparos [--prod] # crea disparos puntuales (Task Scheduler)
                                                      # a kickoff+2h15 por cada partido pendiente
    python sync_polla.py recordatorio-60min [--prod] # manda el correo "faltan 60 min" a los 10
                                                      # (uso: disparo puntual programado a primer_kickoff-60min)
    python sync_polla.py recordatorio-faltantes [--prod] # manda "aún no has predicho" solo a
                                                      # quien tiene 0 predicciones en la fecha
                                                      # (uso: disparo puntual programado AL primer_kickoff)
    python sync_polla.py logos [--prod]              # cachea escudos (equipos nuevos que aún no tengan logo)
    python sync_polla.py notificaciones [--prod]     # procesa correos pendientes y sus reintentos

Por defecto usa .env (base de DESARROLLO). Agregar --prod para operar sobre la
polla REAL (usa .env.prod) — solo cuando el cambio ya esté probado en dev.

Reusa el scraper de 10-prediction/src/sofascore.py y predecir.py (no se duplica lógica).
"""
import sys
from pathlib import Path

ES_PROD = "--prod" in sys.argv
if ES_PROD:
    sys.argv.remove("--prod")

RAIZ_PROYECTOS = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else None
PRED_SRC = RAIZ_PROYECTOS / "00_Gestion_procesos_vm" / "10-prediction" / "src" if RAIZ_PROYECTOS else None
if PRED_SRC and PRED_SRC.exists():
    sys.path.insert(0, str(PRED_SRC))  # monorepo local (dev): sofascore.py + predecir.py completos
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "_vendor"))  # CI: solo sofascore.py vendorizado
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 11-polla-ligapro/ para db.py

from dotenv import load_dotenv
ARCHIVO_ENV = ".env.prod" if ES_PROD else ".env"
load_dotenv(Path(__file__).resolve().parents[1] / ARCHIVO_ENV)
print(f"[ambiente: {'PRODUCCIÓN' if ES_PROD else 'desarrollo'} — {ARCHIVO_ENV}]")

from sofascore import SofaScore, TOURN, SEASONS  # noqa: E402
from db import get_client  # noqa: E402
from services.predictions import refresh_round_deadlines  # noqa: E402
from email_notif import send_html  # noqa: E402
from services.notification_worker import process_notifications  # noqa: E402
from services.notification_payloads import (  # noqa: E402
    enqueue_all_predicted, enqueue_missing_predictions_reminder, enqueue_polla_finished,
    enqueue_polla_tied, enqueue_reminder_60min, enqueue_round_finished,
)


def numero_polla(ronda: int) -> int:
    """Misma agrupación que usa la app (Reglamento Polla Papers: 5 fechas por polla)."""
    return (ronda - 1) // 5 + 1


def rango_polla(numero: int) -> tuple[int, int]:
    inicio = (numero - 1) * 5 + 1
    return inicio, inicio + 4


# Al terminar la fase de todos-contra-todos (fecha_ronda 1-30), la Liga Pro
# Ecuador 2026 divide la tabla en 3 grupos (Championship/Qualifying/
# Relegation Round), cada uno un sub-torneo de SofaScore con su PROPIO
# roundInfo.round independiente (pueden desincronizarse entre sí). Por eso,
# desde fecha_ronda 31 en adelante ya no filtramos por round: agrupamos los
# próximos partidos de los 3 grupos por cercanía de kickoff (8 partidos por
# fecha: 3 Championship + 2 Qualifying + 3 Relegation).
INICIO_FASE_GRUPOS = 31
PARTIDOS_POR_FECHA_FASE_GRUPOS = 8


def sync_fixture(anio=2026, max_partidos=10, ronda=None):
    """Trae próximos partidos de SofaScore y los inserta/actualiza en Supabase.

    `ronda` es siempre el número de fecha de la Polla. Desde INICIO_FASE_GRUPOS
    ya no existe un único "round" válido para los 3 grupos a la vez, así que
    se ignora el roundInfo de SofaScore y se toman los próximos
    PARTIDOS_POR_FECHA_FASE_GRUPOS eventos más cercanos en el tiempo (de
    cualquier grupo) como la fecha pedida.
    """
    from predecir import proximos_partidos  # requiere el monorepo local (10-prediction/src)
    print("Consultando próximos partidos en SofaScore...")
    fase_grupos = ronda is not None and ronda >= INICIO_FASE_GRUPOS
    ronda_sofascore = None if fase_grupos else ronda
    # En fase de grupos, proximos_partidos() corta a max_partidos ANTES de que
    # podamos reordenar por fecha (mezcla los 3 sub-torneos según el orden en
    # que SofaScore los pagina, no por kickoff) — se pide un margen amplio de
    # próximas fechas y se recorta ya ordenado, abajo.
    pedir = PARTIDOS_POR_FECHA_FASE_GRUPOS * 6 if fase_grupos else max_partidos
    partidos = proximos_partidos(anio=anio, max_partidos=pedir, con_odds=False, ronda=ronda_sofascore)
    if not partidos:
        print("No se encontraron próximos partidos.")
        return

    if fase_grupos:
        partidos = sorted(partidos, key=lambda p: p["fecha"])[:PARTIDOS_POR_FECHA_FASE_GRUPOS]
        for p in partidos:
            print(f"  [grupo] {p['grupo']}: {p['local']} vs {p['visitante']} ({p['fecha']})")

    db = get_client()
    rondas_actualizadas = set()
    for p in partidos:
        ronda_polla = ronda if fase_grupos else p["ronda"]
        fila = {
            "event_id": p["event_id"],
            "fecha_ronda": ronda_polla,
            "kickoff": p["fecha"].isoformat(),
            # Placeholder para la columna not-null: refresh_round_deadlines()
            # la recalcula bien (regla de toda la ronda) justo abajo.
            "cierre_predicciones": p["fecha"].isoformat(),
            "local": p["local"],
            "visita": p["visitante"],
            "local_id": p["local_id"],
            "visita_id": p["visitante_id"],
            "cerrado": False,
        }
        db.table("partidos").upsert(fila, on_conflict="event_id").execute()
        if ronda_polla is not None:
            rondas_actualizadas.add(ronda_polla)
        print(f"  [ok] {p['local']} vs {p['visitante']}  (fecha {ronda_polla}, {p['fecha']})")
    for ronda_actualizada in rondas_actualizadas:
        refresh_round_deadlines(db, ronda_actualizada)
    print(f"\n{len(partidos)} partidos sincronizados a Supabase.")


MARGEN_FIN_PARTIDO_MIN = 135  # 2h de partido + 15 min de margen (ver programar_disparos_puntuales)
VENTANA_PARTIDO_HORAS = MARGEN_FIN_PARTIDO_MIN / 60  # misma ventana, en horas (ver hay_partido_en_ventana)


def programar_disparos_puntuales():
    """Crea, vía Task Scheduler, un disparo puntual (ONCE) por cada partido
    sin resultado: a kickoff + MARGEN_FIN_PARTIDO_MIN. Así el sync corre justo
    cuando el partido ya debería haber terminado, en vez de sondear cada
    15 min durante toda la ventana. Delega en PowerShell (Register-
    ScheduledTask con un DateTime real) en vez de "schtasks /SD" para no
    depender del formato de fecha corta configurado en el sistema. Solo
    funciona en Windows (esta PC) — nombres de tarea únicos por event_id
    Y por ambiente (dev/prod comparten el mismo Task Scheduler de esta PC:
    sin el sufijo, probar en dev pisaba el horario real de producción), así
    que correr esto varias veces no crea duplicados (se usa -Force, que
    sobrescribe con el mismo horario si ya existía)."""
    import subprocess
    from datetime import datetime, timezone, timedelta

    db = get_client()
    pendientes = db.table("partidos").select("event_id, local, visita, kickoff").is_("gl_real", "null").execute().data
    ahora = datetime.now(timezone.utc)

    bat = str(Path(__file__).resolve().parent / "sync_resultados_task.bat")
    sufijo_ambiente = "" if ES_PROD else "_dev"
    creadas = pasadas = fallidas = 0
    for p in pendientes:
        ko = datetime.fromisoformat(p["kickoff"].replace("Z", "+00:00"))
        disparo = ko + timedelta(minutes=MARGEN_FIN_PARTIDO_MIN)
        if disparo <= ahora:
            pasadas += 1
            continue
        disparo_local = disparo.astimezone()
        nombre_tarea = f"PollaLigaPro_Resultado_{p['event_id']}{sufijo_ambiente}"
        ps = (
            f'$action = New-ScheduledTaskAction -Execute "{bat}"; '
            f'$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date "{disparo_local.isoformat()}"); '
            f'$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) '
            f'-StartWhenAvailable; '
            f'Register-ScheduledTask -TaskName "{nombre_tarea}" -Action $action -Trigger $trigger '
            f'-Settings $settings -Description "Disparo puntual Polla Liga Pro: {p["local"]} vs {p["visita"]}" -Force | Out-Null'
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        if res.returncode == 0:
            creadas += 1
            print(f"  [ok] {p['local']} vs {p['visita']} -> disparo {disparo_local.strftime('%d/%m %H:%M')}")
        else:
            fallidas += 1
            print(f"  [!] {p['local']} vs {p['visita']}: {res.stderr.strip()}")

    print(f"\n{creadas} tareas creadas/actualizadas, {pasadas} con horario ya pasado "
          f"(se cubren con el sync de 3h), {fallidas} fallidas.")


def programar_recordatorio_60min():
    """Crea, vía Task Scheduler, un disparo puntual (ONCE) para el correo de
    "faltan 60 min" de cada fecha con partidos aún no jugados: se dispara a
    (kickoff del primer partido de esa fecha) - 60 min. Un único disparo por
    fecha (no por partido) — nombre de tarea único por fecha_ronda Y por
    ambiente (dev/prod comparten el mismo Task Scheduler de esta PC: sin el
    sufijo, probar en dev pisaba el horario real de producción), así que
    correr esto varias veces no crea duplicados (usa -Force)."""
    import subprocess
    from datetime import datetime, timezone, timedelta

    db = get_client()
    pendientes = (db.table("partidos").select("fecha_ronda, kickoff")
                  .is_("gl_real", "null").not_.is_("fecha_ronda", "null").execute().data)
    ahora = datetime.now(timezone.utc)

    primer_kickoff_por_ronda = {}
    for p in pendientes:
        ko = datetime.fromisoformat(p["kickoff"].replace("Z", "+00:00"))
        actual = primer_kickoff_por_ronda.get(p["fecha_ronda"])
        if actual is None or ko < actual:
            primer_kickoff_por_ronda[p["fecha_ronda"]] = ko

    bat = str(Path(__file__).resolve().parent / "sync_recordatorio_task.bat")
    sufijo_ambiente = "" if ES_PROD else "_dev"
    creadas = pasadas = fallidas = 0
    for ronda, primer_ko in primer_kickoff_por_ronda.items():
        disparo = primer_ko - timedelta(minutes=60)
        if disparo <= ahora:
            pasadas += 1
            continue
        disparo_local = disparo.astimezone()
        nombre_tarea = f"PollaLigaPro_Recordatorio60_{ronda}{sufijo_ambiente}"
        ps = (
            f'$action = New-ScheduledTaskAction -Execute "{bat}"; '
            f'$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date "{disparo_local.isoformat()}"); '
            f'$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) '
            f'-StartWhenAvailable; '
            f'Register-ScheduledTask -TaskName "{nombre_tarea}" -Action $action -Trigger $trigger '
            f'-Settings $settings -Description "Recordatorio 60min Polla Liga Pro: Fecha {ronda}" -Force | Out-Null'
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        if res.returncode == 0:
            creadas += 1
            print(f"  [ok] Fecha {ronda} -> recordatorio {disparo_local.strftime('%d/%m %H:%M')}")
        else:
            fallidas += 1
            print(f"  [!] Fecha {ronda}: {res.stderr.strip()}")

    print(f"\n{creadas} recordatorios de 60min creados/actualizados, {pasadas} con horario ya pasado, "
          f"{fallidas} fallidos.")


def programar_recordatorio_faltantes():
    """Crea, vía Task Scheduler, un disparo puntual (ONCE) para el correo
    "aún no has predicho" de cada fecha con partidos aún no jugados: se
    dispara justo AL kickoff del PRIMER partido de la fecha — aviso
    temprano para quien todavía no predijo nada. El plazo real de cierre de
    la fecha es el kickoff del 2° partido (ver cerrar_por_kickoff()), pero
    este correo dispara antes, al primero, a propósito. Un único disparo
    por fecha — nombre de tarea único por fecha_ronda Y por ambiente
    (dev/prod comparten el mismo Task Scheduler de esta PC: sin el sufijo,
    probar en dev pisaba el horario real de producción), así que correr
    esto varias veces no crea duplicados (usa -Force)."""
    import subprocess
    from datetime import datetime, timezone

    db = get_client()
    # Primer kickoff HISTÓRICO de cada ronda activa (no el primer
    # pendiente): si el partido 1 ya jugó pero quedan 2-8 sin resultado, el
    # disparo de este correo sigue siendo "al kickoff del partido 1", no del
    # próximo pendiente.
    rondas_activas = {p["fecha_ronda"] for p in
                       db.table("partidos").select("fecha_ronda").is_("gl_real", "null")
                       .not_.is_("fecha_ronda", "null").execute().data}
    todos_de_rondas_activas = (db.table("partidos").select("fecha_ronda, kickoff")
                                .in_("fecha_ronda", list(rondas_activas)).execute().data
                                if rondas_activas else [])
    ahora = datetime.now(timezone.utc)

    primer_kickoff_por_ronda = {}
    for p in todos_de_rondas_activas:
        ko = datetime.fromisoformat(p["kickoff"].replace("Z", "+00:00"))
        actual = primer_kickoff_por_ronda.get(p["fecha_ronda"])
        if actual is None or ko < actual:
            primer_kickoff_por_ronda[p["fecha_ronda"]] = ko

    bat = str(Path(__file__).resolve().parent / "sync_recordatorio_faltantes_task.bat")
    sufijo_ambiente = "" if ES_PROD else "_dev"
    creadas = pasadas = fallidas = 0
    for ronda, primer_ko in primer_kickoff_por_ronda.items():
        disparo = primer_ko
        if disparo <= ahora:
            pasadas += 1
            continue
        disparo_local = disparo.astimezone()
        nombre_tarea = f"PollaLigaPro_RecordatorioFaltantes_{ronda}{sufijo_ambiente}"
        ps = (
            f'$action = New-ScheduledTaskAction -Execute "{bat}"; '
            f'$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date "{disparo_local.isoformat()}"); '
            f'$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) '
            f'-StartWhenAvailable; '
            f'Register-ScheduledTask -TaskName "{nombre_tarea}" -Action $action -Trigger $trigger '
            f'-Settings $settings -Description "Recordatorio faltantes Polla Liga Pro: Fecha {ronda}" -Force | Out-Null'
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        if res.returncode == 0:
            creadas += 1
            print(f"  [ok] Fecha {ronda} -> recordatorio faltantes {disparo_local.strftime('%d/%m %H:%M')}")
        else:
            fallidas += 1
            print(f"  [!] Fecha {ronda}: {res.stderr.strip()}")

    print(f"\n{creadas} recordatorios de faltantes creados/actualizados, {pasadas} con horario ya pasado, "
          f"{fallidas} fallidos.")


def enviar_recordatorio_faltantes():
    """Manda el correo "aún no has predicho" solo a jugadores con 0
    predicciones en la fecha, disparado cuando el PRIMER partido de la
    fecha ya cerró — aviso temprano (el plazo real de cierre de la fecha
    es el kickoff del 2° partido, ver cerrar_por_kickoff()). Idempotente
    vía notificaciones_enviadas (tipo "recordatorio_faltantes") — una sola
    vez por fecha."""
    db = get_client()
    # Todos los partidos de rondas aún no cerradas del todo (al menos un
    # partido sin resultado) — no solo los partidos sin resultado, porque
    # necesitamos ver si el PRIMER partido histórico de la fecha ya cerró,
    # aunque ya tenga resultado y esté fuera de "pendientes".
    rondas_activas = {p["fecha_ronda"] for p in
                       db.table("partidos").select("fecha_ronda").is_("gl_real", "null")
                       .not_.is_("fecha_ronda", "null").execute().data}
    partidos = (db.table("partidos").select("id, fecha_ronda, kickoff, local, visita, cerrado")
                .in_("fecha_ronda", list(rondas_activas)).execute().data
                if rondas_activas else [])
    por_ronda = {}
    for p in partidos:
        por_ronda.setdefault(p["fecha_ronda"], []).append(p)

    ya_notificadas = {
        n["fecha_ronda"] for n in
        db.table("notificaciones_enviadas").select("fecha_ronda").eq("tipo", "recordatorio_faltantes").execute().data
    }

    for ronda, partidos_ronda in por_ronda.items():
        if ronda in ya_notificadas:
            continue
        partidos_ronda_ord = sorted(partidos_ronda, key=lambda p: p["kickoff"])
        if not partidos_ronda_ord or not partidos_ronda_ord[0]["cerrado"]:
            continue  # el 1° partido de la fecha aún no cerró — no es momento de avisar

        try:
            db.table("notificaciones_enviadas").insert(
                {"fecha_ronda": ronda, "tipo": "recordatorio_faltantes"}).execute()
        except Exception:
            continue  # ya notificada por otra corrida en paralelo — no reenviar

        ids_ronda = [p["id"] for p in partidos_ronda_ord]
        preds = (db.table("predicciones").select("jugador_id").in_("partido_id", ids_ronda).execute().data
                 if ids_ronda else [])
        jugadores_con_prediccion = {pr["jugador_id"] for pr in preds}

        pendientes_ronda = [p for p in partidos_ronda_ord if not p["cerrado"]]
        lista_partidos = [
            {"local": p["local"], "visita": p["visita"], "hora": _hora_ecuador_hm(p["kickoff"])}
            for p in pendientes_ronda
        ]

        jugadores = db.table("jugadores").select("id, nombre, email").execute().data
        faltantes = [j for j in jugadores if j["id"] not in jugadores_con_prediccion and j["email"]]
        for j in faltantes:
            enqueue_missing_predictions_reminder(db, j["email"], j["id"], j["nombre"], ronda, lista_partidos, len(ids_ronda))
        print(f"  [ok] recordatorio de faltantes encolado — Fecha {ronda} ({len(faltantes)} jugadores)")


def enviar_recordatorios_60min():
    """Manda el correo de "faltan 60 min" a los 10 jugadores para la fecha
    cuyo primer partido arranca dentro de la próxima hora. Idempotente vía
    notificaciones_enviadas (tipo "recordatorio_60min") — si el disparo
    puntual se reintenta o corre dos veces, no reenvía."""
    db = get_client()
    partidos = (db.table("partidos").select("id, fecha_ronda, kickoff, local, visita")
                .is_("gl_real", "null").not_.is_("fecha_ronda", "null").execute().data)
    por_ronda = {}
    for p in partidos:
        por_ronda.setdefault(p["fecha_ronda"], []).append(p)

    ya_notificadas = {
        n["fecha_ronda"] for n in
        db.table("notificaciones_enviadas").select("fecha_ronda").eq("tipo", "recordatorio_60min").execute().data
    }

    for ronda, partidos_ronda in por_ronda.items():
        if ronda in ya_notificadas:
            continue
        partidos_ronda_ord = sorted(partidos_ronda, key=lambda p: p["kickoff"])

        try:
            db.table("notificaciones_enviadas").insert(
                {"fecha_ronda": ronda, "tipo": "recordatorio_60min"}).execute()
        except Exception:
            continue  # ya notificada por otra corrida en paralelo — no reenviar

        lista_partidos = [
            {"local": p["local"], "visita": p["visita"], "hora": _hora_ecuador_hm(p["kickoff"])}
            for p in partidos_ronda_ord
        ]

        ini, fin = rango_polla(numero_polla(ronda))
        ids_polla = [p["id"] for p in
                     db.table("partidos").select("id, fecha_ronda")
                     .execute().data if p["fecha_ronda"] is not None and ini <= p["fecha_ronda"] <= fin]
        puntos_filas = (db.table("v_puntos").select("jugador_id, puntos, es_exacto")
                         .in_("partido_id", ids_polla).not_.is_("puntos", "null").execute().data
                         if ids_polla else [])
        agregados = {}
        for f in puntos_filas:
            acc = agregados.setdefault(f["jugador_id"], {"puntos": 0, "exactos": 0})
            acc["puntos"] += f["puntos"]
            acc["exactos"] += 1 if f["es_exacto"] else 0

        jugadores = db.table("jugadores").select("id, nombre, email").execute().data
        ranking = sorted(
            [{"id": j["id"], "nombre": j["nombre"], **agregados.get(j["id"], {"puntos": 0, "exactos": 0})}
             for j in jugadores],
            key=lambda r: (-r["puntos"], -r["exactos"]))
        # Primera fecha de una polla nueva: nadie tiene puntos aún — no hay
        # top 3 real (sería un podio ficticio, por orden arbitrario de id).
        hay_puntos = any(r["puntos"] > 0 for r in ranking)
        top3 = [r["nombre"] for r in ranking[:3]] if hay_puntos else []
        nombres_top3 = set(top3)

        for j in jugadores:
            if not j["email"]:
                continue
            enqueue_reminder_60min(db, j["email"], j["id"], j["nombre"], ronda, lista_partidos,
                                    top3, j["nombre"] in nombres_top3)
        print(f"  [ok] recordatorio 60min encolado — Fecha {ronda} "
              f"({sum(1 for j in jugadores if j['email'])} jugadores)")

        sufijo_ambiente = "" if ES_PROD else "_dev"
        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Unregister-ScheduledTask -TaskName "PollaLigaPro_Recordatorio60_{ronda}{sufijo_ambiente}" '
             f'-Confirm:$false -ErrorAction SilentlyContinue'],
            capture_output=True, text=True)


def limpiar_disparos_completados():
    """Borra las tareas ONCE de partidos que ya tienen resultado — Task
    Scheduler no las elimina solo al dispararse, solo quedan inactivas."""
    import subprocess
    db = get_client()
    con_resultado = db.table("partidos").select("event_id").not_.is_("gl_real", "null").execute().data
    sufijo_ambiente = "" if ES_PROD else "_dev"
    borradas = 0
    for p in con_resultado:
        nombre_tarea = f"PollaLigaPro_Resultado_{p['event_id']}{sufijo_ambiente}"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Unregister-ScheduledTask -TaskName "{nombre_tarea}" -Confirm:$false -ErrorAction SilentlyContinue'],
            capture_output=True, text=True)
        if res.returncode == 0:
            borradas += 1
    if borradas:
        print(f"{borradas} disparos puntuales ya completados fueron limpiados.")


def hay_partido_en_ventana():
    """True si algún partido sin resultado ya arrancó (kickoff pasado) y sigue
    dentro de la ventana en la que podría terminar (< VENTANA_PARTIDO_HORAS).
    Consulta liviana a Supabase (sin Playwright) — permite que la tarea de
    alta frecuencia decida si vale la pena abrir el navegador o no."""
    from datetime import datetime, timezone, timedelta
    db = get_client()
    pendientes = db.table("partidos").select("kickoff").is_("gl_real", "null").execute().data
    ahora = datetime.now(timezone.utc)
    for p in pendientes:
        ko = datetime.fromisoformat(p["kickoff"].replace("Z", "+00:00"))
        if ko <= ahora <= ko + timedelta(hours=VENTANA_PARTIDO_HORAS):
            return True
    return False


def sync_resultados(anio=2026):
    """Baja resultados finalizados de SofaScore y actualiza marcadores + cierra
    partidos. También refresca el kickoff de partidos aún no jugados: cuando
    se carga un fixture nuevo, SofaScore a veces solo confirma la fecha de la
    ronda y da un horario provisional por partido — el horario definitivo se
    publica después, y sync_fixture() solo corre una vez por ronda, así que
    sin este refresco el kickoff guardado queda desactualizado en silencio
    (bug real: los 8 partidos de Fecha 27 quedaron con el mismo timestamp
    provisional, y un jugador alcanzó a predecir después del kickoff real de
    uno de ellos porque el bloqueo de la app usa el kickoff guardado)."""
    from datetime import datetime, timezone
    db = get_client()
    pendientes = db.table("partidos").select("*").is_("gl_real", "null").execute().data
    if not pendientes:
        print("No hay partidos pendientes de resultado en la base.")
        return
    ids_pendientes = {p["event_id"] for p in pendientes}
    kickoff_actual = {p["event_id"]: p["kickoff"] for p in pendientes}
    ronda_por_evento = {p["event_id"]: p["fecha_ronda"] for p in pendientes}
    print(f"Partidos pendientes de resultado: {len(ids_pendientes)}")

    actualizados = 0
    kickoffs_corregidos = 0
    rondas_con_kickoff_corregido = set()
    with SofaScore() as sofa:
        pagina = 0
        while True:
            r = sofa.fetch_json(f"/api/v1/unique-tournament/{TOURN}/season/{SEASONS[anio]}/events/last/{pagina}")
            evs = r.get("events", [])
            for ev in evs:
                eid = ev["id"]
                if eid not in ids_pendientes:
                    continue
                # El endpoint "events/last" trae partidos en cualquier estado
                # (en vivo, entretiempo, finalizado) — homeScore/awayScore ya
                # existen con el marcador PARCIAL mientras el partido sigue
                # jugándose. Sin este filtro, un sync que corre a media hora
                # de fútbol grababa ese parcial como si fuera el resultado
                # final y el partido, ya con gl_real no-nulo, quedaba fuera
                # de "pendientes" para siempre — nunca se corregía solo.
                if ev.get("status", {}).get("type") != "finished":
                    continue
                hs = ev.get("homeScore", {}).get("current")
                as_ = ev.get("awayScore", {}).get("current")
                if hs is None or as_ is None:
                    continue
                db.table("partidos").update({
                    "gl_real": hs, "gv_real": as_, "cerrado": True,
                }).eq("event_id", eid).execute()
                actualizados += 1
                print(f"  [ok] {ev['homeTeam']['name']} {hs}-{as_} {ev['awayTeam']['name']}")
            if not r.get("hasNextPage") or not evs:
                break
            pagina += 1
            sofa.page.wait_for_timeout(400)

        pagina = 0
        while True:
            r = sofa.fetch_json(f"/api/v1/unique-tournament/{TOURN}/season/{SEASONS[anio]}/events/next/{pagina}")
            evs = r.get("events", [])
            for ev in evs:
                eid = ev["id"]
                if eid not in ids_pendientes:
                    continue
                dt_real = datetime.fromtimestamp(ev["startTimestamp"], tz=timezone.utc)
                kickoff_guardado = kickoff_actual.get(eid)
                dt_guardado = (datetime.fromisoformat(kickoff_guardado.replace("Z", "+00:00"))
                               if kickoff_guardado else None)
                if dt_guardado != dt_real:
                    kickoff_real = dt_real.isoformat()
                    db.table("partidos").update({"kickoff": kickoff_real}).eq("event_id", eid).execute()
                    kickoffs_corregidos += 1
                    if ronda_por_evento[eid] is not None:
                        rondas_con_kickoff_corregido.add(ronda_por_evento[eid])
                    print(f"  [kickoff] {ev['homeTeam']['name']} vs {ev['awayTeam']['name']}: "
                          f"{kickoff_actual.get(eid)} -> {kickoff_real}")
            if not r.get("hasNextPage") or not evs:
                break
            pagina += 1
            sofa.page.wait_for_timeout(400)

    print(f"\n{actualizados} partidos actualizados con resultado real.")
    if kickoffs_corregidos:
        for ronda_corregida in rondas_con_kickoff_corregido:
            refresh_round_deadlines(db, ronda_corregida)
        print(f"{kickoffs_corregidos} kickoffs corregidos con el horario real de SofaScore.")


def _hora_ecuador(kickoff_iso: str) -> str:
    """Ecuador no tiene horario de verano, así que el offset fijo -5h siempre
    es correcto — evita depender de tzdata en el runner de CI (igual que
    a_local() en app.py, pero sin pandas/tzdata como camino principal)."""
    import pandas as pd
    from datetime import timezone, timedelta
    t = pd.to_datetime(kickoff_iso)
    return t.tz_convert(timezone(timedelta(hours=-5))).strftime("%a %d/%m")


def _hora_ecuador_hm(kickoff_iso: str) -> str:
    """Como _hora_ecuador() pero con hora incluida (para listar partidos en
    orden de kickoff con su horario exacto)."""
    import pandas as pd
    from datetime import timezone, timedelta
    t = pd.to_datetime(kickoff_iso)
    return t.tz_convert(timezone(timedelta(hours=-5))).strftime("%a %d/%m %H:%M")


def notificar_fechas_terminadas():
    """Manda el correo de resultados+tabla a las fechas que se acaban de
    completar (todos sus partidos ya tienen resultado real) y aún no fueron
    notificadas. Se corre después de sync_resultados() en cada ejecución del
    workflow — así no depende de que alguien abra la app."""
    db = get_client()
    partidos = (db.table("partidos")
                .select("id, fecha_ronda, kickoff, local, visita, gl_real, gv_real").execute().data)
    por_ronda = {}
    for p in partidos:
        if p["fecha_ronda"] is not None:
            por_ronda.setdefault(p["fecha_ronda"], []).append(p)

    ya_notificadas = {
        n["fecha_ronda"] for n in
        db.table("notificaciones_enviadas").select("fecha_ronda").eq("tipo", "fecha_terminada").execute().data
    }

    for ronda, partidos_ronda in por_ronda.items():
        if ronda in ya_notificadas:
            continue
        if not partidos_ronda or any(p["gl_real"] is None for p in partidos_ronda):
            continue  # fecha aún no completa

        try:
            db.table("notificaciones_enviadas").insert(
                {"fecha_ronda": ronda, "tipo": "fecha_terminada"}).execute()
        except Exception:
            continue  # ya notificada por otra corrida en paralelo — no reenviar

        partidos_ronda_ord = sorted(partidos_ronda, key=lambda p: p["local"])
        ids_ronda = [p["id"] for p in partidos_ronda_ord]

        ini, fin = rango_polla(numero_polla(ronda))
        ids_polla = [p["id"] for p in partidos if p["fecha_ronda"] is not None and ini <= p["fecha_ronda"] <= fin]
        puntos_filas = (db.table("v_puntos").select("jugador_id, partido_id, puntos, es_exacto")
                         .in_("partido_id", ids_polla).not_.is_("puntos", "null").execute().data
                         if ids_polla else [])
        agregados = {}
        for f in puntos_filas:
            acc = agregados.setdefault(f["jugador_id"], {"puntos": 0, "exactos": 0, "jugados": 0})
            acc["puntos"] += f["puntos"]
            acc["exactos"] += 1 if f["es_exacto"] else 0
            acc["jugados"] += 1

        # predicciones + puntos de la ronda recién terminada, por jugador y partido
        preds_ronda = (db.table("predicciones").select("jugador_id, partido_id, gl_pred, gv_pred")
                        .in_("partido_id", ids_ronda).execute().data
                        if ids_ronda else [])
        preds_por_jugador = {}
        for pr in preds_ronda:
            preds_por_jugador.setdefault(pr["jugador_id"], {})[pr["partido_id"]] = pr
        puntos_ronda_por_jugador = {}
        for f in puntos_filas:
            if f["partido_id"] in ids_ronda:
                puntos_ronda_por_jugador.setdefault(f["jugador_id"], {})[f["partido_id"]] = f

        jugadores = db.table("jugadores").select("id, nombre, email").execute().data
        ranking = sorted(
            [{"nombre": j["nombre"], **agregados.get(j["id"], {"puntos": 0, "exactos": 0, "jugados": 0})}
             for j in jugadores],
            key=lambda r: (-r["puntos"], -r["exactos"]))

        for j in jugadores:
            if not j["email"]:
                continue
            preds_j = preds_por_jugador.get(j["id"], {})
            puntos_j = puntos_ronda_por_jugador.get(j["id"], {})
            resultados = []
            for p in partidos_ronda_ord:
                pr = preds_j.get(p["id"])
                vp = puntos_j.get(p["id"])
                resultados.append({
                    "local": p["local"], "visita": p["visita"], "gl": p["gl_real"], "gv": p["gv_real"],
                    "fecha": _hora_ecuador(p["kickoff"]),
                    "gl_pred": pr["gl_pred"] if pr else None,
                    "gv_pred": pr["gv_pred"] if pr else None,
                    "puntos": vp["puntos"] if vp else None,
                    "es_exacto": vp["es_exacto"] if vp else False,
                })
            enqueue_round_finished(db, j["email"], j["id"], j["nombre"], ronda, resultados, ranking)
        print(f"  [ok] correo de fecha terminada encolado — Fecha {ronda} "
              f"({sum(1 for j in jugadores if j['email'])} jugadores)")

        # Si esta fecha es la última de su polla (bloque de 5), encolar
        # además el correo de cierre de la polla completa — un solo correo
        # extra por jugador, aparte del de "fecha terminada" de arriba.
        if ronda == fin:
            nombres_por_id = {j["id"]: j["nombre"] for j in jugadores}
            top5 = sorted(
                [{"nombre": nombres_por_id[jid], "puntos": d["puntos"], "exactos": d["exactos"]}
                 for jid, d in agregados.items()],
                key=lambda r: (-r["puntos"], -r["exactos"]))[:5]
            if top5:
                # Reglamento (numeral 7): un empate en puntos en el 1er
                # puesto NO se declara ganador directo — se resuelve con 3
                # partidos adicionales que elige el Administrador. Así que
                # solo se declara ganador cuando el 1er puesto es único;
                # si hay empate, se avisa el empate y se espera el desempate.
                empatados_top1 = [f for f in top5 if f["puntos"] == top5[0]["puntos"]]
                hay_empate = len(empatados_top1) > 1
                for j in jugadores:
                    if not j["email"]:
                        continue
                    if hay_empate:
                        enqueue_polla_tied(db, j["email"], j["id"], ronda, numero_polla(ronda), ini, fin, empatados_top1)
                    else:
                        enqueue_polla_finished(db, j["email"], j["id"], ronda, numero_polla(ronda), ini, fin, top5)
                if hay_empate:
                    print(f"  [ok] correo de EMPATE en la Polla {numero_polla(ronda)} encolado "
                          f"({sum(1 for j in jugadores if j['email'])} jugadores) — pendiente desempate manual")
                else:
                    print(f"  [ok] correo de ganadores de la Polla {numero_polla(ronda)} encolado "
                          f"({sum(1 for j in jugadores if j['email'])} jugadores)")

        # Al cerrar una fecha, cargar automáticamente la siguiente si aún no
        # existe en la base — evita que quede sin subir hasta que alguien lo
        # note y lo pida a mano (pasó con la Fecha 28 tras cerrar la 27).
        # Cada paso va en su propio try/except: si sync_fixture() sube el
        # fixture pero programar_disparos_puntuales() o
        # programar_recordatorio_60min() fallan (ej. Task Scheduler no
        # disponible justo al arrancar la PC tras estar apagada), los pasos
        # siguientes deben intentarse igual en vez de quedar silenciados por
        # una excepción compartida (pasó con el recordatorio de Fecha 29).
        siguiente = ronda + 1
        ya_existe = db.table("partidos").select("id").eq("fecha_ronda", siguiente).limit(1).execute().data
        if not ya_existe:
            print(f"  Fecha {ronda} terminada — cargando automáticamente Fecha {siguiente}...")
            fixture_ok = False
            try:
                sync_fixture(ronda=siguiente)
                fixture_ok = True
            except Exception as e:
                print(f"  [!] No se pudo cargar el fixture de la Fecha {siguiente}: {e}")
            if fixture_ok:
                try:
                    programar_disparos_puntuales()
                except Exception as e:
                    print(f"  [!] No se pudieron programar los disparos de resultado de la Fecha {siguiente}: {e}")
                try:
                    programar_recordatorio_60min()
                except Exception as e:
                    print(f"  [!] No se pudo programar el recordatorio de 60min de la Fecha {siguiente}: {e}")
                try:
                    programar_recordatorio_faltantes()
                except Exception as e:
                    print(f"  [!] No se pudo programar el recordatorio de faltantes de la Fecha {siguiente}: {e}")


def sync_logos():
    """Descarga y cachea escudos de equipo + logo de la liga (base64) en Supabase.

    Necesario porque la API de imágenes de SofaScore está detrás de Cloudflare
    y bloquea hotlinking directo (403 aunque se manden Referer/User-Agent) —
    solo responde a un navegador que ya pasó el challenge, como el que arma
    SofaScore() acá. La app web (sin Playwright) sirve estas imágenes cacheadas.
    """
    db = get_client()
    partidos = db.table("partidos").select("local_id, visita_id").execute().data
    ids_equipos = ({p["local_id"] for p in partidos if p["local_id"]} |
                    {p["visita_id"] for p in partidos if p["visita_id"]})
    ya_cacheados = {e["id"] for e in db.table("equipos").select("id").execute().data}

    objetivos = [(tid, f"/api/v1/team/{tid}/image") for tid in ids_equipos if tid not in ya_cacheados]
    if TOURN not in ya_cacheados:
        objetivos.append((TOURN, f"/api/v1/unique-tournament/{TOURN}/image"))

    if not objetivos:
        print("Todos los escudos ya están cacheados.")
        return

    print(f"Descargando {len(objetivos)} escudos...")
    js = """async (p) => {
        const r = await fetch(p);
        if (r.status !== 200) return {status: r.status, body: null};
        const buf = await r.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
        return {status: 200, body: btoa(binary)};
    }"""
    with SofaScore() as sofa:
        for tid, path in objetivos:
            res = sofa.page.evaluate(js, path)
            if res["status"] == 200 and res["body"]:
                db.table("equipos").upsert({"id": tid, "logo_base64": res["body"]}).execute()
                print(f"  [ok] id {tid}")
            else:
                print(f"  [!] id {tid} -> status {res['status']}")
            sofa.page.wait_for_timeout(300)
    print("Listo.")


def cerrar_por_kickoff():
    """Cierra (bloquea predicciones) los partidos según la política de plazo
    de la fecha: los partidos 1° y 2° de cada fecha se cierran cada uno en
    SU propio kickoff (igual que antes); del 3° en adelante quedan abiertos
    hasta el kickoff del 2° partido de esa misma fecha — ahí se cierran
    todos de golpe, dando a los jugadores el plazo de "2 partidos" para
    completar toda la fecha en vez de perder cada partido a su propia hora."""
    from datetime import datetime, timezone
    db = get_client()
    ahora = datetime.now(timezone.utc).isoformat()

    abiertos = (db.table("partidos").select("id, cierre_predicciones")
                .eq("cerrado", False).execute().data)
    ids_a_cerrar = [
        partido["id"] for partido in abiertos
        if partido["cierre_predicciones"] <= ahora
    ]

    if ids_a_cerrar:
        db.table("partidos").update({"cerrado": True}).in_("id", ids_a_cerrar).execute()
    print(f"{len(ids_a_cerrar)} partidos cerrados por haber iniciado (plazo: 1°/2° a su kickoff, "
          f"3°+ al kickoff del 2°).")


def notificar_fechas_bloqueadas():
    """Encola la revelación al iniciar el segundo partido de cada fecha.

    No exige que todos hayan predicho: el cierre del segundo kickoff es el
    evento que congela la fecha y revela las predicciones disponibles.
    """
    from datetime import datetime, timezone
    db = get_client()
    ahora = datetime.now(timezone.utc)
    partidos = db.table("partidos").select("id,fecha_ronda,kickoff,local,visita").execute().data or []
    jugadores = db.table("jugadores").select("id,nombre,email").execute().data or []
    por_ronda = {}
    for p in partidos:
        if p["fecha_ronda"] is not None:
            por_ronda.setdefault(p["fecha_ronda"], []).append(p)
    ya = {n["fecha_ronda"] for n in db.table("notificaciones_enviadas").select("fecha_ronda")
          .eq("tipo", "todos_predijeron").execute().data}
    nombres = {j["id"]: j["nombre"] for j in jugadores}
    for ronda, grupo in por_ronda.items():
        orden = sorted(grupo, key=lambda p: p["kickoff"])
        if len(orden) < 2 or datetime.fromisoformat(orden[1]["kickoff"].replace("Z", "+00:00")) > ahora or ronda in ya:
            continue
        try:
            db.table("notificaciones_enviadas").insert({"fecha_ronda": ronda, "tipo": "todos_predijeron"}).execute()
        except Exception as error:
            print(f"  [!] revelación Fecha {ronda}: no se pudo crear el candado ({error})")
            continue
        ids = [p["id"] for p in orden]
        preds = db.table("predicciones").select("jugador_id,partido_id,gl_pred,gv_pred").in_("partido_id", ids).execute().data or []
        por_partido = {pid: {"local": [], "empate": [], "visita": []} for pid in ids}
        for pr in preds:
            clave = "empate" if pr["gl_pred"] == pr["gv_pred"] else ("local" if pr["gl_pred"] > pr["gv_pred"] else "visita")
            por_partido[pr["partido_id"]][clave].append({"nombre": nombres.get(pr["jugador_id"], "Jugador"), "gl": pr["gl_pred"], "gv": pr["gv_pred"], "es_exacto": False})
        matches = [{"local": p["local"], "visita": p["visita"], "grupos": por_partido[p["id"]]} for p in orden]
        for m in matches:
            for lista in m["grupos"].values():
                lista.sort(key=lambda x: x["nombre"])
        for j in jugadores:
            if j.get("email"):
                enqueue_all_predicted(db, j["email"], j["id"], ronda, matches)
        print(f"  [ok] revelación encolada — Fecha {ronda}")


def procesar_notificaciones():
    """Envía trabajos pendientes de la cola sin bloquear a la aplicación web."""
    resumen = process_notifications(get_client(), send_html)
    print("Notificaciones: " + ", ".join(f"{clave}={valor}" for clave, valor in resumen.items()))


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else None
    if modo == "fixture":
        ronda = int(sys.argv[2]) if len(sys.argv) > 2 else None
        sync_fixture(ronda=ronda)
        programar_disparos_puntuales()
        programar_recordatorio_60min()
        programar_recordatorio_faltantes()
    elif modo == "resultados":
        sync_resultados()
        cerrar_por_kickoff()
        notificar_fechas_bloqueadas()
        notificar_fechas_terminadas()
        limpiar_disparos_completados()
    elif modo == "resultados-si-en-ventana":
        # Para la tarea de alta frecuencia (cada 15-20 min): solo abre
        # Playwright/SofaScore si hay un partido que ya arrancó y podría
        # haber terminado — evita cargar la PC y golpear SofaScore fuera
        # de horario de partidos.
        if hay_partido_en_ventana():
            sync_resultados()
            cerrar_por_kickoff()
            notificar_fechas_bloqueadas()
            notificar_fechas_terminadas()
        else:
            print("Sin partidos en ventana activa — se omite esta corrida.")
    elif modo == "programar-disparos":
        programar_disparos_puntuales()
        programar_recordatorio_60min()
        programar_recordatorio_faltantes()
    elif modo == "recordatorio-60min":
        enviar_recordatorios_60min()
    elif modo == "recordatorio-faltantes":
        enviar_recordatorio_faltantes()
    elif modo == "cerrar":
        cerrar_por_kickoff()
    elif modo == "logos":
        sync_logos()
    elif modo == "notificaciones":
        procesar_notificaciones()
    else:
        print(__doc__)
