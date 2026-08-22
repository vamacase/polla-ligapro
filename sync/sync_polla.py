"""
SYNC POLLA — corre en tu PC (necesita Playwright para pasar Cloudflare de SofaScore).

Uso:
    python sync_polla.py fixture [ronda] [--prod]   # sube próximos partidos (predecibles)
    python sync_polla.py resultados [--prod]        # actualiza marcadores reales + cierra partidos
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
from email_notif import enviar_fecha_terminada  # noqa: E402


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


def sync_resultados(anio=2026):
    """Baja resultados finalizados de SofaScore y actualiza marcadores + cierra partidos."""
    db = get_client()
    pendientes = db.table("partidos").select("*").is_("gl_real", "null").execute().data
    if not pendientes:
        print("No hay partidos pendientes de resultado en la base.")
        return
    ids_pendientes = {p["event_id"] for p in pendientes}
    print(f"Partidos pendientes de resultado: {len(ids_pendientes)}")

    actualizados = 0
    with SofaScore() as sofa:
        pagina = 0
        while True:
            r = sofa.fetch_json(f"/api/v1/unique-tournament/{TOURN}/season/{SEASONS[anio]}/events/last/{pagina}")
            evs = r.get("events", [])
            for ev in evs:
                eid = ev["id"]
                if eid not in ids_pendientes:
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

    print(f"\n{actualizados} partidos actualizados con resultado real.")


def _hora_ecuador(kickoff_iso: str) -> str:
    """Ecuador no tiene horario de verano, así que el offset fijo -5h siempre
    es correcto — evita depender de tzdata en el runner de CI (igual que
    a_local() en app.py, pero sin pandas/tzdata como camino principal)."""
    import pandas as pd
    from datetime import timezone, timedelta
    t = pd.to_datetime(kickoff_iso)
    return t.tz_convert(timezone(timedelta(hours=-5))).strftime("%a %d/%m")


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

        resultados = sorted(
            [{"local": p["local"], "visita": p["visita"], "gl": p["gl_real"], "gv": p["gv_real"],
              "fecha": _hora_ecuador(p["kickoff"])}
             for p in partidos_ronda],
            key=lambda r: r["local"])

        ini, fin = rango_polla(numero_polla(ronda))
        ids_polla = [p["id"] for p in partidos if p["fecha_ronda"] is not None and ini <= p["fecha_ronda"] <= fin]
        puntos_filas = (db.table("v_puntos").select("jugador_id, puntos, es_exacto")
                         .in_("partido_id", ids_polla).not_.is_("puntos", "null").execute().data
                         if ids_polla else [])
        agregados = {}
        for f in puntos_filas:
            acc = agregados.setdefault(f["jugador_id"], {"puntos": 0, "exactos": 0, "jugados": 0})
            acc["puntos"] += f["puntos"]
            acc["exactos"] += 1 if f["es_exacto"] else 0
            acc["jugados"] += 1

        jugadores = db.table("jugadores").select("id, nombre, email").execute().data
        ranking = sorted(
            [{"nombre": j["nombre"], **agregados.get(j["id"], {"puntos": 0, "exactos": 0, "jugados": 0})}
             for j in jugadores],
            key=lambda r: (-r["puntos"], -r["exactos"]))

        destinatarios = [j["email"] for j in jugadores if j["email"]]
        if destinatarios:
            enviar_fecha_terminada(destinatarios, ronda, resultados, ranking)
            print(f"  [ok] correo de fecha terminada enviado — Fecha {ronda}")


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
    elif modo == "resultados":
        sync_resultados()
        cerrar_por_kickoff()
        notificar_fechas_terminadas()
    elif modo == "cerrar":
        cerrar_por_kickoff()
    elif modo == "logos":
        sync_logos()
    else:
        print(__doc__)
