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
    python sync_polla.py logos [--prod]              # cachea escudos (equipos nuevos que aún no tengan logo)

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
from email_notif import enviar_fecha_terminada, enviar_recordatorio_60min  # noqa: E402


def numero_polla(ronda: int) -> int:
    """Misma agrupación que usa la app (Reglamento Polla Papers: 5 fechas por polla)."""
    return (ronda - 1) // 5 + 1


def rango_polla(numero: int) -> tuple[int, int]:
    inicio = (numero - 1) * 5 + 1
    return inicio, inicio + 4


def sync_fixture(anio=2026, max_partidos=10, ronda=None):
    """Trae próximos partidos de SofaScore y los inserta/actualiza en Supabase."""
    from predecir import proximos_partidos  # requiere el monorepo local (10-prediction/src)
    print("Consultando próximos partidos en SofaScore...")
    partidos = proximos_partidos(anio=anio, max_partidos=max_partidos, con_odds=False, ronda=ronda)
    if not partidos:
        print("No se encontraron próximos partidos.")
        return

    db = get_client()
    for p in partidos:
        fila = {
            "event_id": p["event_id"],
            "fecha_ronda": p["ronda"],
            "kickoff": p["fecha"].isoformat(),
            "local": p["local"],
            "visita": p["visitante"],
            "local_id": p["local_id"],
            "visita_id": p["visitante_id"],
            "cerrado": False,
        }
        db.table("partidos").upsert(fila, on_conflict="event_id").execute()
        print(f"  [ok] {p['local']} vs {p['visitante']}  (ronda {p['ronda']}, {p['fecha']})")
    print(f"\n{len(partidos)} partidos sincronizados a Supabase.")


MARGEN_FIN_PARTIDO_MIN = 135  # 2h de partido + 15 min de margen (ver programar_disparos_puntuales)


def programar_disparos_puntuales():
    """Crea, vía Task Scheduler, un disparo puntual (ONCE) por cada partido
    sin resultado: a kickoff + MARGEN_FIN_PARTIDO_MIN. Así el sync corre justo
    cuando el partido ya debería haber terminado, en vez de sondear cada
    15 min durante toda la ventana. Delega en PowerShell (Register-
    ScheduledTask con un DateTime real) en vez de "schtasks /SD" para no
    depender del formato de fecha corta configurado en el sistema. Solo
    funciona en Windows (esta PC) — nombres de tarea únicos por event_id, así
    que correr esto varias veces no crea duplicados (se usa -Force, que
    sobrescribe con el mismo horario si ya existía)."""
    import subprocess
    from datetime import datetime, timezone, timedelta

    db = get_client()
    pendientes = db.table("partidos").select("event_id, local, visita, kickoff").is_("gl_real", "null").execute().data
    ahora = datetime.now(timezone.utc)

    bat = str(Path(__file__).resolve().parent / "sync_resultados_task.bat")
    creadas = pasadas = fallidas = 0
    for p in pendientes:
        ko = datetime.fromisoformat(p["kickoff"].replace("Z", "+00:00"))
        disparo = ko + timedelta(minutes=MARGEN_FIN_PARTIDO_MIN)
        if disparo <= ahora:
            pasadas += 1
            continue
        disparo_local = disparo.astimezone()
        nombre_tarea = f"PollaLigaPro_Resultado_{p['event_id']}"
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
    fecha (no por partido) — nombre de tarea único por fecha_ronda, así que
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
    creadas = pasadas = fallidas = 0
    for ronda, primer_ko in primer_kickoff_por_ronda.items():
        disparo = primer_ko - timedelta(minutes=60)
        if disparo <= ahora:
            pasadas += 1
            continue
        disparo_local = disparo.astimezone()
        nombre_tarea = f"PollaLigaPro_Recordatorio60_{ronda}"
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
            enviar_recordatorio_60min(j["email"], j["nombre"], ronda, lista_partidos,
                                       top3, j["nombre"] in nombres_top3)
        print(f"  [ok] recordatorio 60min enviado — Fecha {ronda} "
              f"({sum(1 for j in jugadores if j['email'])} jugadores)")

        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'Unregister-ScheduledTask -TaskName "PollaLigaPro_Recordatorio60_{ronda}" '
             f'-Confirm:$false -ErrorAction SilentlyContinue'],
            capture_output=True, text=True)


def limpiar_disparos_completados():
    """Borra las tareas ONCE de partidos que ya tienen resultado — Task
    Scheduler no las elimina solo al dispararse, solo quedan inactivas."""
    import subprocess
    db = get_client()
    con_resultado = db.table("partidos").select("event_id").not_.is_("gl_real", "null").execute().data
    borradas = 0
    for p in con_resultado:
        nombre_tarea = f"PollaLigaPro_Resultado_{p['event_id']}"
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
    print(f"Partidos pendientes de resultado: {len(ids_pendientes)}")

    actualizados = 0
    kickoffs_corregidos = 0
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
                    print(f"  [kickoff] {ev['homeTeam']['name']} vs {ev['awayTeam']['name']}: "
                          f"{kickoff_actual.get(eid)} -> {kickoff_real}")
            if not r.get("hasNextPage") or not evs:
                break
            pagina += 1
            sofa.page.wait_for_timeout(400)

    print(f"\n{actualizados} partidos actualizados con resultado real.")
    if kickoffs_corregidos:
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
            enviar_fecha_terminada(j["email"], j["nombre"], ronda, resultados, ranking)
        print(f"  [ok] correo de fecha terminada enviado — Fecha {ronda} "
              f"({sum(1 for j in jugadores if j['email'])} jugadores)")

        # Al cerrar una fecha, cargar automáticamente la siguiente si aún no
        # existe en la base — evita que quede sin subir hasta que alguien lo
        # note y lo pida a mano (pasó con la Fecha 28 tras cerrar la 27).
        siguiente = ronda + 1
        ya_existe = db.table("partidos").select("id").eq("fecha_ronda", siguiente).limit(1).execute().data
        if not ya_existe:
            try:
                print(f"  Fecha {ronda} terminada — cargando automáticamente Fecha {siguiente}...")
                sync_fixture(ronda=siguiente)
                programar_disparos_puntuales()
                programar_recordatorio_60min()
            except Exception as e:
                print(f"  [!] No se pudo cargar automáticamente la Fecha {siguiente}: {e}")


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
    """Cierra (bloquea predicciones) los partidos cuyo kickoff ya pasó, aunque no haya resultado aún."""
    from datetime import datetime, timezone
    db = get_client()
    ahora = datetime.now(timezone.utc).isoformat()
    res = db.table("partidos").update({"cerrado": True}).lt("kickoff", ahora).eq("cerrado", False).execute()
    print(f"{len(res.data)} partidos cerrados por haber iniciado.")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else None
    if modo == "fixture":
        ronda = int(sys.argv[2]) if len(sys.argv) > 2 else None
        sync_fixture(ronda=ronda)
        programar_disparos_puntuales()
        programar_recordatorio_60min()
    elif modo == "resultados":
        sync_resultados()
        cerrar_por_kickoff()
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
            notificar_fechas_terminadas()
        else:
            print("Sin partidos en ventana activa — se omite esta corrida.")
    elif modo == "programar-disparos":
        programar_disparos_puntuales()
        programar_recordatorio_60min()
    elif modo == "recordatorio-60min":
        enviar_recordatorios_60min()
    elif modo == "cerrar":
        cerrar_por_kickoff()
    elif modo == "logos":
        sync_logos()
    else:
        print(__doc__)
