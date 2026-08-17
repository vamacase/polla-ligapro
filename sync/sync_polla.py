"""
SYNC POLLA — corre en tu PC (necesita Playwright para pasar Cloudflare de SofaScore).

Uso:
    python sync_polla.py fixture [ronda]   # sube próximos partidos (predecibles)
    python sync_polla.py resultados        # actualiza marcadores reales + cierra partidos

Reusa el scraper de 10-prediction/src/sofascore.py y predecir.py (no se duplica lógica).
"""
import sys
from pathlib import Path

RAIZ_PROYECTOS = Path(__file__).resolve().parents[3]  # .../01_vicente
PRED_SRC = RAIZ_PROYECTOS / "00_Gestion_procesos_vm" / "10-prediction" / "src"
sys.path.insert(0, str(PRED_SRC))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 11-polla-ligapro/ para db.py

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sofascore import SofaScore, TOURN, SEASONS  # noqa: E402
from predecir import proximos_partidos  # noqa: E402
from db import get_client  # noqa: E402


def sync_fixture(anio=2026, max_partidos=10, ronda=None):
    """Trae próximos partidos de SofaScore y los inserta/actualiza en Supabase."""
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
    elif modo == "cerrar":
        cerrar_por_kickoff()
    else:
        print(__doc__)
