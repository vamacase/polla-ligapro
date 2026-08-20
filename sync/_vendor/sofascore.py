"""
SCRAPER SOFASCORE — Liga Pro Ecuador
====================================

Técnica: abrimos sofascore.com con un navegador REAL (Playwright). El navegador
pasa el challenge de Cloudflare una vez; luego hacemos fetch a su API interna
DESDE DENTRO del navegador (mismo origen, ya con cookies válidas). Esto es
mucho más robusto que curl (que da 403).

USO RESPONSABLE:
    - Solo para aprendizaje personal, sin redistribuir ni uso comercial.
    - Pausas entre requests (PAUSA_MS) para no sobrecargar el servidor.
    - Caché en disco: nunca re-pedimos algo que ya bajamos.

IDs útiles (LigaPro Primera A Ecuador):
    unique-tournament = 240
    seasons: 2021=35552, 2022=40503, 2023=48720, 2024=58043, 2025=71184, 2026=89674

Endpoints usados:
    /api/v1/unique-tournament/240/season/<SID>/events/last/<page>   -> partidos jugados
    /api/v1/event/<eid>/statistics                                  -> stats del partido

Salidas:
    datos/processed/partidos_EC1.csv   (resultados; compatible con el pipeline)
    datos/raw/sofa_stats_EC1.json      (caché de stats por partido)
"""
from pathlib import Path
import json
import time
import pandas as pd
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
DIR_PROCESSED = RAIZ / "datos" / "processed"
DIR_RAW = RAIZ / "datos" / "raw"
DIR_PROCESSED.mkdir(parents=True, exist_ok=True)
DIR_RAW.mkdir(parents=True, exist_ok=True)
CACHE_STATS = DIR_RAW / "sofa_stats_EC1.json"

TOURN = 240
SEASONS = {2021: 35552, 2022: 40503, 2023: 48720, 2024: 58043, 2025: 71184, 2026: 89674}
PAUSA_MS = 600  # cortesía entre requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class SofaScore:
    """Context manager: abre el navegador, pasa Cloudflare, ofrece fetch_json."""
    def __init__(self, headless=False):
        self.headless = headless

    def __enter__(self):
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"])
        self.ctx = self.browser.new_context(
            user_agent=UA, locale="es-EC", viewport={"width": 1366, "height": 768})
        self.page = self.ctx.new_page()
        self.page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=60000)
        for _ in range(30):
            self.page.wait_for_timeout(1000)
            if "moment" not in self.page.title().lower():
                break
        else:
            raise RuntimeError("No se pudo pasar Cloudflare de SofaScore.")
        return self

    def __exit__(self, *a):
        try:
            self.browser.close()
        finally:
            self._pw.stop()

    def fetch_json(self, path):
        js = """async (p) => { const r = await fetch(p, {headers:{'Accept':'application/json'}});
                return {status:r.status, body: await r.text()}; }"""
        res = self.page.evaluate(js, path)
        if res["status"] == 200:
            return json.loads(res["body"])
        return {"_status": res["status"]}


# ---------------------------------------------------------------------------
# 1) RESULTADOS de una temporada -> DataFrame compatible con el pipeline
# ---------------------------------------------------------------------------
def _eventos_temporada(sofa: "SofaScore", season_id: int):
    eventos, pagina = [], 0
    while True:
        r = sofa.fetch_json(
            f"/api/v1/unique-tournament/{TOURN}/season/{season_id}/events/last/{pagina}")
        evs = r.get("events", [])
        eventos.extend(evs)
        if not r.get("hasNextPage") or not evs:
            break
        pagina += 1
        sofa.page.wait_for_timeout(PAUSA_MS)
    return eventos


def descargar_resultados(temporadas=(2021, 2022, 2023, 2024)) -> pd.DataFrame:
    filas = []
    with SofaScore() as sofa:
        for anio in temporadas:
            sid = SEASONS[anio]
            evs = _eventos_temporada(sofa, sid)
            print(f"  {anio}: {len(evs)} partidos")
            for ev in evs:
                # Solo partidos finalizados con marcador
                hs = ev.get("homeScore", {}).get("current")
                as_ = ev.get("awayScore", {}).get("current")
                if hs is None or as_ is None:
                    continue
                ftr = "H" if hs > as_ else ("A" if as_ > hs else "D")
                filas.append({
                    "event_id": ev["id"],
                    "Date": pd.to_datetime(ev["startTimestamp"], unit="s"),
                    "HomeTeam": ev["homeTeam"]["name"],
                    "AwayTeam": ev["awayTeam"]["name"],
                    "FTHG": hs, "FTAG": as_, "FTR": ftr,
                    "Temporada": str(anio), "Liga": "EC1",
                })
            sofa.page.wait_for_timeout(PAUSA_MS)

    df = pd.DataFrame(filas).sort_values("Date").reset_index(drop=True)
    salida = DIR_PROCESSED / "partidos_EC1.csv"
    df.to_csv(salida, index=False)
    print(f"\nResultados: {len(df)} partidos -> {salida}")
    print(df["FTR"].value_counts(normalize=True).round(3).to_string())
    return df


# ---------------------------------------------------------------------------
# 2) STATS por partido (con caché). Extrae "Match overview" en un dict plano.
# ---------------------------------------------------------------------------
STATS_UTILES = {
    "Ball possession", "Total shots", "Shots on target", "Big chances",
    "Corner kicks", "Fouls", "Passes", "Accurate passes",
    "Touches in penalty area",
}


def _cargar_cache():
    return json.loads(CACHE_STATS.read_text(encoding="utf-8")) if CACHE_STATS.exists() else {}


def _num(v):
    """'72%' -> 72.0 ; '410/500 (82%)' -> 410.0 ; 25 -> 25.0."""
    if v is None:
        return None
    s = str(v)
    if "%" in s and "/" not in s:
        try: return float(s.replace("%", "").strip())
        except ValueError: return None
    if "/" in s:  # '410/500 (82%)' -> tomamos el primer número
        try: return float(s.split("/")[0].strip())
        except ValueError: return None
    try: return float(s)
    except ValueError: return None


def descargar_stats(max_requests=200):
    """Baja stats de los partidos en partidos_EC1.csv que aún no estén en caché."""
    df = pd.read_csv(DIR_PROCESSED / "partidos_EC1.csv")
    if "event_id" not in df.columns:
        raise RuntimeError("partidos_EC1.csv no tiene event_id. Corre descargar_resultados primero.")

    cache = _cargar_cache()
    ids = [str(i) for i in df["event_id"].tolist()]
    pendientes = [i for i in ids if i not in cache]
    print(f"Partidos totales: {len(ids)} | en caché: {len(ids)-len(pendientes)} | pendientes: {len(pendientes)}")

    usados = 0
    with SofaScore() as sofa:
        for eid in pendientes:
            if usados >= max_requests:
                print(f"  [tope] {max_requests} requests esta corrida.")
                break
            st = sofa.fetch_json(f"/api/v1/event/{eid}/statistics")
            usados += 1
            grupos = st.get("statistics", [])
            if not grupos:
                cache[eid] = None
            else:
                registro = {}
                for g in grupos[0].get("groups", []):
                    for it in g.get("statisticsItems", []):
                        if it.get("name") in STATS_UTILES:
                            registro[f"home_{it['name']}"] = _num(it.get("home"))
                            registro[f"away_{it['name']}"] = _num(it.get("away"))
                cache[eid] = registro or None
            if usados % 25 == 0:
                CACHE_STATS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  ...{usados} requests")
            sofa.page.wait_for_timeout(PAUSA_MS)

    CACHE_STATS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    con = sum(1 for v in cache.values() if v)
    print(f"\nCorrida: {usados} requests. Caché: {con}/{len(cache)} partidos con stats -> {CACHE_STATS}")
    return cache


# ---------------------------------------------------------------------------
# 3) CUOTAS HISTÓRICAS 1X2 por partido (con caché)
# ---------------------------------------------------------------------------
CACHE_ODDS = DIR_RAW / "sofa_odds_EC1.json"


def _frac_a_decimal(frac: str):
    """'24/25' -> 1.96 (cuota decimal)."""
    try:
        n, d = frac.split("/")
        return float(n) / float(d) + 1.0
    except Exception:
        return None


def descargar_odds(max_requests=2000, pausa_ms=None):
    """
    Baja las cuotas 1X2 de cada partido en partidos_EC1.csv que no estén en caché.
    Guarda, por partido, las 3 cuotas decimales {1, X, 2}.

    Resiliente: si un fetch falla (rate-limit / conexión), guarda el caché,
    espera un poco más y sigue con el siguiente. Reanudable: el caché evita
    re-pedir lo ya bajado.
    """
    pausa = pausa_ms if pausa_ms is not None else PAUSA_MS
    df = pd.read_csv(DIR_PROCESSED / "partidos_EC1.csv")
    cache = json.loads(CACHE_ODDS.read_text(encoding="utf-8")) if CACHE_ODDS.exists() else {}
    ids = [str(i) for i in df["event_id"].tolist()]
    pendientes = [i for i in ids if i not in cache]
    print(f"Partidos: {len(ids)} | en caché: {len(ids)-len(pendientes)} | pendientes: {len(pendientes)}")

    usados = fallos = 0
    with SofaScore() as sofa:
        for eid in pendientes:
            if usados >= max_requests:
                print(f"  [tope] {max_requests} requests esta corrida.")
                break
            try:
                o = sofa.fetch_json(f"/api/v1/event/{eid}/odds/1/all")
                fallos = 0
            except Exception as e:
                fallos += 1
                CACHE_ODDS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  [!] Fallo ({type(e).__name__}); caché guardado. Espera larga y sigo...")
                sofa.page.wait_for_timeout(5000)
                if fallos >= 8:
                    print("  [x] Demasiados fallos seguidos; corto la corrida (reanudable).")
                    break
                continue
            usados += 1
            mr = None
            for m in o.get("markets", []):
                if m.get("marketGroup") == "1X2" or m.get("marketName") == "Full time":
                    mr = m
                    break
            if not mr:
                cache[eid] = None
            else:
                dec = {}
                for ch in mr.get("choices", []):
                    dec[ch["name"]] = _frac_a_decimal(ch.get("fractionalValue", ""))
                cache[eid] = dec if {"1", "X", "2"}.issubset(dec) and all(dec.values()) else None
            if usados % 25 == 0:
                CACHE_ODDS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  ...{usados} requests")
            sofa.page.wait_for_timeout(pausa)

    CACHE_ODDS.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    con = sum(1 for v in cache.values() if v)
    print(f"\nCorrida: {usados} requests. Caché: {con}/{len(cache)} partidos con cuotas -> {CACHE_ODDS}")
    return cache


if __name__ == "__main__":
    import sys
    modo = sys.argv[1] if len(sys.argv) > 1 else "resultados"
    if modo == "resultados":
        # Todas las temporadas disponibles (2026 en curso se actualiza cada vez).
        descargar_resultados((2021, 2022, 2023, 2024, 2025, 2026))
    elif modo == "stats":
        descargar_stats(max_requests=int(sys.argv[2]) if len(sys.argv) > 2 else 200)
    elif modo == "odds":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
        pausa = int(sys.argv[3]) if len(sys.argv) > 3 else None
        descargar_odds(max_requests=n, pausa_ms=pausa)
    else:
        print("Uso: python sofascore.py [resultados|stats [N]|odds [N]]")
