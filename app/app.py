"""Polla Liga Pro Ecuador — webapp Streamlit (predicciones + ranking entre amigos)."""
import os
import hmac
import importlib
import sys
import time
from html import escape
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from db import get_client  # noqa: E402
from core.scoring import add_score_to_ranking, score_display  # noqa: E402
import core.results_view as results_view  # noqa: E402
# Streamlit reruns this script in a persistent Python process. Reload this
# small presentation module so a Cloud deployment never keeps its old result
# renderer in sys.modules after app.py has been updated.
importlib.reload(results_view)
render_resultado = results_view.render_resultado
from services.auth import (  # noqa: E402
    autenticar_jugador, cambiar_pin, jugador_de_sesion, sign_session, validar_pin,
)
from services.predictions import save_prediction  # noqa: E402
from services.notification_payloads import build_reveal_matches, enqueue_all_predicted, enqueue_confirmation  # noqa: E402
from streamlit_cookies_controller import CookieController  # noqa: E402

st.set_page_config(page_title="Polla Liga Pro", page_icon="⚽", layout="centered")

DIAS_SESION = 30
COOKIE_SESION = "polla_sesion"
ERROR_ACCESO = "No se pudo iniciar sesión. Revisa tus datos o inténtalo más tarde."


def cookies():
    # CookieController cachea internamente en st.session_state["cookies"],
    # así que basta con construirlo cada vez (no es costoso: no repite la
    # llamada al componente JS mientras esa key siga en session_state).
    # En algunos reruns el componente puede dejar ese cache en None en vez
    # de {} — se limpia antes de instanciar para no romper get()/set().
    if st.session_state.get("cookies") is None:
        st.session_state.pop("cookies", None)
    return CookieController()

TZ_EC = "America/Guayaquil"
LIGA_ID = 240  # unique-tournament de LigaPro Ecuador en SofaScore; también la
                # clave usada para su logo en la tabla equipos (mismo espacio
                # de ids que los team_id, sin colisión real posible).

# --- CSS consolidado (paleta verde salvia + crema) ------------------------
# Nota: las clases .st-key-<key> son API pública de Streamlit (verificado en
# 1.60.0) para estilar contenedores individuales via key=. Las reglas sobre
# data-testid internos (ej. stNumberInput) NO tienen garantía de estabilidad
# entre versiones — se mantienen al mínimo y solo cosméticas.
st.markdown("""
<style>
:root {
  --polla-bg:#F7F7F2; --polla-card:#FFFFFF; --polla-accent:#6B9080;
  --polla-text:#2F3E38; --polla-muted:#7A8A83; --polla-border:#E3E3DA;
  --polla-exacto:#7FB09A; --polla-1x2:#E4C580; --polla-fallo:#D89A9A;
}

/* Sombra sutil en tarjetas (inspirado en la densidad visual de casas de
   apuestas: tarjeta blanca elevada sobre fondo gris/crema, sin depender
   solo del borde para separar contenido). [class*=] porque .st-key-<key>
   se aplica al bloque interno, no al wrapper con el borde. */
[class*="st-key-card_partido_"], [class*="st-key-card_resultado_"],
[class*="st-key-card_mipred_"] {
  box-shadow: 0 1px 3px rgba(47, 62, 56, 0.08);
  border-radius: 0.75rem;
}

/* Fila compacta de pronóstico móvil: escudo y su marcador por equipo
   en vez de equipo arriba/input abajo por
   separado — menos alto que la tarjeta vertical anterior. No se intenta
   poner ambos equipos lado a lado: Streamlit apila st.columns en una sola
   columna vertical bajo cierto ancho SIN importar cuántas haya (incluso
   2, comprobado), y tampoco es fiable forzarlo por CSS porque Streamlit
   recalcula el flex-flow de sus bloques por JS en cada resize. */
[class*="st-key-card_partido_"] { padding-top:0.5rem !important; padding-bottom:0.5rem !important; }
.polla-fila-hora { font-size:0.72rem; color:var(--polla-muted); }
.polla-fila-equipo {
  display:flex; align-items:center; gap:0.35rem;
  font-size:0.8em; color:var(--polla-text); font-weight:600;
  overflow:hidden; min-width:0; margin-top:0.3rem;
}
.polla-fila-equipo span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.polla-fila-equipo img { flex-shrink:0; }
.polla-fila-equipo { margin-top:0; font-size:0.9rem; }
/* Fila escudo+nombre+marcador: nunca se parte en dos líneas; el nombre
   se recorta con "…" (st-key-fila_gl_<id> / fila_gv_<id>). */
[class*="st-key-fila_gl_"], [class*="st-key-fila_gv_"] { flex-wrap:nowrap !important; }
[class*="st-key-fila_gl_"] > *, [class*="st-key-fila_gv_"] > * { min-width:0; }
.polla-fila-cabecera {
  display:flex; align-items:center; justify-content:space-between; gap:0.5rem;
}
.polla-saludo {
  display:flex; align-items:center; gap:0.6rem; font-size:1.15rem; color:var(--polla-text);
}
.polla-progreso {
  padding:0.55rem 0.8rem; border-radius:0.75rem; font-size:0.9rem;
  background:#F3EEDD; color:var(--polla-text); border:1px solid #E8DFC2;
}
.polla-progreso--ok { background:#E8F0EB; border-color:#CFE0D6; }
.polla-confirmar-fila {
  display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); gap:0.6rem;
  align-items:center; padding:0.35rem 0; border-bottom:1px solid var(--polla-border);
  font-size:0.88rem;
}
.polla-confirmar-fila span:first-child { text-align:right; }
.polla-confirmar-fila--cero { background:#F3EEDD; border-radius:0.4rem; }
.polla-confirmar-fila b { font-variant-numeric:tabular-nums; }

.polla-equipo { text-align:center; min-height:4.6rem; }
.polla-equipo img { display:block; margin:0 auto; }
.polla-equipo span { font-size:0.82em; color:var(--polla-text); }

.polla-vs {
  display:flex; align-items:center; justify-content:center;
  height:100%; color:var(--polla-muted); font-weight:600;
}

.polla-badge {
  display:inline-block; padding:0.15rem 0.6rem; border-radius:999px;
  font-size:0.75rem; font-weight:600; background:var(--polla-accent);
  color:#fff;
}
.polla-badge--urgente { background:var(--polla-fallo); color:#4A2E2E; }
.polla-badge--cerrado { background:#E3E3DA; color:var(--polla-muted); }

.polla-pill {
  display:inline-block; padding:0.2rem 0.7rem; border-radius:999px;
  font-weight:700; font-size:0.9rem; color:#2F3E38;
}
.polla-pill--exacto { background:var(--polla-exacto); }
.polla-pill--1x2 { background:var(--polla-1x2); }
.polla-pill--fallo { background:var(--polla-fallo); }
.polla-pill--na { background:#E3E3DA; color:var(--polla-muted); }

.polla-scoreline {
  display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);
  align-items:center; gap:0.45rem; width:100%;
}
.polla-score-team {
  display:flex; align-items:center; gap:0.35rem; min-width:0;
  color:var(--polla-text); font-size:0.88rem; font-weight:600;
}
.polla-score-team--local { justify-content:flex-end; text-align:right; }
.polla-score-team--visita { justify-content:flex-start; text-align:left; }
.polla-score-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.polla-score-team img { flex:0 0 auto; object-fit:contain; }
.polla-score-pair {
  display:flex; align-items:center; justify-content:center; gap:0.3rem;
  min-width:3.8rem; padding:0.25rem 0.45rem; border-radius:0.55rem;
  border:1px solid var(--polla-border); background:var(--polla-card);
  color:var(--polla-text); font-size:1.05rem; font-weight:750; font-variant-numeric:tabular-nums;
}
.polla-score-separator { color:var(--polla-muted); font-weight:500; }
.polla-score--ganador {
  padding:0.08rem 0.28rem; border-radius:0.35rem;
  background:var(--polla-exacto); color:var(--polla-text); font-weight:800;
}

.polla-rank-row {
  display:flex; align-items:center; gap:0.7rem;
  padding:0.5rem 0.8rem; border-radius:0.75rem; margin-bottom:0.4rem;
  background:var(--polla-card); border:1px solid var(--polla-border);
}
.polla-rank-row--yo {
  border-left:4px solid var(--polla-accent);
  background:#EEF3F0;
}
.polla-medalla { font-size:1.3rem; width:1.8rem; text-align:center; }

/* Columna del grupo que acertó el resultado real, en la revelación por
   partido (agrupado local/empate/visita). [class*=] porque .st-key-<key>
   se aplica al bloque interno del st.container, no al wrapper con borde. */
[class*="st-key-grupo_correcto_"] {
  border-color: var(--polla-accent) !important;
  border-width: 2px !important;
}

@media (max-width: 640px) {
    .block-container { padding-left: 0.8rem; padding-right: 0.8rem; padding-bottom: 5.5rem !important; }
    div[data-testid="stNumberInput"] input { font-size: 1rem; padding: 0.5rem; }
    h3 { font-size: 1.1rem; }
    .polla-equipo { min-height: 4rem; }
    .polla-scoreline { gap:0.25rem; }
    .polla-score-team { gap:0.2rem; font-size:0.8rem; }
    .polla-score-pair { min-width:3.4rem; padding:0.2rem 0.35rem; }
    /* El selector de vistas (key="nav" → clase pública .st-key-nav) pasa a
       ser la barra de navegación inferior; en escritorio queda arriba. */
    .st-key-nav {
        position:fixed; left:0; right:0; bottom:0; z-index:1000000;
        padding:0.35rem 0.2rem max(0.45rem, env(safe-area-inset-bottom));
        background:var(--polla-card); border-top:1px solid var(--polla-border);
        box-shadow:0 -2px 10px rgba(47, 62, 56, 0.10);
    }
    .st-key-nav > div, .st-key-nav div:has(> button) {
        display:flex; flex-wrap:nowrap; width:100%; gap:0.15rem;
    }
    .st-key-nav button {
        display:flex; flex:1 1 0; flex-direction:column; align-items:center;
        justify-content:center; min-width:0; min-height:2.9rem; padding:0.25rem 0.1rem;
        border:0 !important; border-radius:0.6rem !important;
        font-size:0.66rem; line-height:1.1; white-space:normal;
    }
    .st-key-nav button > div, .st-key-nav button > div > span {
        display:flex; flex-direction:column; align-items:center; gap:0.1rem; min-width:0;
    }
    .st-key-nav button p { font-size:0.64rem; white-space:nowrap; letter-spacing:-0.01em; margin:0; }
    .st-key-nav button [data-testid="stIconMaterial"] { font-size:1.2rem; }
    /* El botón "Deploy" del header de Streamlit Cloud (data-testid
       verificado en 1.64.0) queda por encima del nav inferior con su
       z-index de header por defecto. No aporta nada a los jugadores —
       se oculta en móvil en vez de perseguir z-index. */
    [data-testid="stAppDeployButton"] { display:none !important; }
    /* Badge "Hosted with Streamlit" de Community Cloud: se inyecta fuera
       del árbol de la app (no tiene data-testid propio de Streamlit,
       distinto del botón Deploy de arriba) y también tapa el nav inferior
       en móvil. Su clase/id trae un hash de build que cambia entre
       despliegues — se cubre con varios selectores conocidos del widget
       ("viewer badge") en vez de uno solo, para no depender de un hash
       exacto no verificado. Si alguna variante no aplica en esta versión
       de Streamlit Cloud, las otras igual lo ocultan. */
    #viewerBadge, #stApp-viewer-badge,
    div[id*="viewerBadge"], div[class*="viewerBadge"],
    a[href*="streamlit.io/cloud"],
    a[href^="https://streamlit.io"] { display:none !important; }
    /* Botones +/- del marcador: área táctil de 48px (≥44px recomendado),
       compatible con escudo + nombre + marcador en una sola fila.
       Testids verificados en Streamlit 1.60.0. */
    [data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {
        min-width: 3rem !important;
        min-height: 3rem !important;
    }
    [data-testid="stNumberInputStepUp"] svg, [data-testid="stNumberInputStepDown"] svg {
        width: 1.6rem !important;
        height: 1.6rem !important;
    }
}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def db():
    return get_client()


@st.cache_data(ttl=3600)
def cargar_logos():
    """id (team_id o LIGA_ID) -> logo en base64, cacheado por sync_polla.py logos.

    No se hotlinkea directo a SofaScore: su API de imágenes está detrás de
    Cloudflare y bloquea cualquier <img src> externo (403 aunque se manden
    Referer/User-Agent) — solo responde a un navegador que ya pasó el
    challenge, como el que usa Playwright durante el sync.
    """
    filas = db().table("equipos").select("id, logo_base64").execute().data
    return {f["id"]: f["logo_base64"] for f in filas if f["logo_base64"]}


# Lecturas cacheadas de las vistas de solo consulta. st.cache_data es
# compartido entre TODAS las sesiones: nada de aquí depende del jugador que
# mira, y el TTL corto hace que un resultado nuevo aparezca en <1 min. El
# camino de guardado y la revelación leen siempre sin caché.
@st.cache_data(ttl=300)
def leer_jugadores():
    return db().table("jugadores").select("id, nombre").order("nombre").execute().data


@st.cache_data(ttl=60)
def leer_rondas_partidos():
    return db().table("partidos").select("id, fecha_ronda, cerrado").execute().data


@st.cache_data(ttl=60)
def leer_puntos_partidos(ids_partidos: tuple):
    if not ids_partidos:
        return []
    return (db().table("v_puntos").select("jugador_id, partido_id, puntos, es_exacto")
            .in_("partido_id", list(ids_partidos)).not_.is_("puntos", "null")
            .execute().data)


@st.cache_data(ttl=60)
def leer_resultados_recientes():
    return (db().table("partidos").select("*").eq("cerrado", True).eq("anulado", False)
            .not_.is_("gl_real", "null").order("kickoff", desc=True).limit(20).execute().data)


def logo(team_id, size=48):
    if not team_id:
        return ""
    b64 = cargar_logos().get(team_id)
    if not b64:
        return f'<span style="font-size:{size}px; line-height:1">⚽</span>'
    return f'<img src="data:image/png;base64,{b64}" width="{size}" height="{size}" style="object-fit:contain">'


def a_local(ts) -> pd.Timestamp:
    """Convierte un timestamptz (UTC) a hora de Ecuador."""
    t = pd.to_datetime(ts)
    try:
        return t.tz_convert(TZ_EC)
    except Exception:
        # Fallback si tzdata no está disponible en el runtime (ej. Streamlit
        # Cloud sin el paquete). Ecuador no tiene horario de verano, así que
        # el offset fijo -5h siempre es correcto.
        return t.tz_convert(timezone(timedelta(hours=-5)))


# strftime("%a") depende del locale del servidor y sale en inglés ("Sat").
DIAS_ES = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def dia_hora_local(ts) -> str:
    """'sáb 07/11 14:00' en hora de Ecuador."""
    t = a_local(ts)
    return f"{DIAS_ES[t.weekday()]} {t:%d/%m %H:%M}"


def badge_cuenta_regresiva(kickoff, ahora=None) -> str:
    ahora = ahora or datetime.now(timezone.utc)
    restante = pd.to_datetime(kickoff) - ahora
    segundos = restante.total_seconds()
    if segundos <= 0:
        return '<span class="polla-badge polla-badge--cerrado">cerrado</span>'
    dias = int(segundos // 86400)
    horas = int((segundos % 86400) // 3600)
    minutos = int((segundos % 3600) // 60)
    if dias >= 1:
        texto = f"cierra en {dias}d {horas}h"
    elif horas >= 1:
        texto = f"cierra en {horas}h {minutos}m"
    else:
        texto = f"cierra en {minutos}m"
    clase = "polla-badge polla-badge--urgente" if segundos < 3600 else "polla-badge"
    return f'<span class="{clase}">{texto}</span>'


def pill_puntos(puntos, es_exacto=None) -> str:
    display = score_display(puntos, es_exacto)
    return f'<span class="polla-pill {display.css_class}">{display.label}</span>'


def selector_fecha(rondas, key, label="Selecciona la fecha", ronda_defecto=None):
    opciones = [f"Fecha {r}" if r is not None else "Fecha sin definir" for r in rondas]
    idx_defecto = rondas.index(ronda_defecto) if ronda_defecto in rondas else 0
    idx = st.selectbox(label, range(len(rondas)), format_func=lambda i: opciones[i],
                        index=idx_defecto, key=key)
    return rondas[idx]


def numero_polla(ronda: int) -> int:
    """Cada polla agrupa 5 fechas: 1-5, 6-10, 11-15... (Reglamento Polla Papers)."""
    return (ronda - 1) // 5 + 1


def rango_polla(numero: int) -> tuple[int, int]:
    inicio = (numero - 1) * 5 + 1
    return inicio, inicio + 4


def calcular_estado_prediccion(ronda):
    """Para una fecha, cuenta cuántos partidos predijo cada jugador, contra
    cuántos alcanzó a ver (partidos aún abiertos, más los que ya predijo de
    los que cerraron mientras tanto).

    Si un jugador entra tarde y algunos partidos de la fecha ya cerraron
    (bloqueo normal de kickoff), nunca podrá llegar al total histórico de
    partidos de la fecha — quedaría "incompleto" para siempre aunque haya
    predicho todo lo que estaba a su alcance. "total" por jugador es
    entonces: partidos abiertos + partidos cerrados que él sí predijo (los
    cerrados que no predijo no cuentan ni a favor ni en contra).

    Nunca expone los marcadores que cada quien predijo — solo si ya
    completó su predicción o no — para no arruinar la sorpresa antes de
    que cierren los partidos (ver reglamento: la apuesta debe publicarse
    sin haber visto la de los demás).
    """
    # Un partido anulado no cuenta: sin este filtro, una predicción hecha
    # sobre él marcaba ✅ a quien no había predicho ningún partido real.
    partidos_ronda = (db().table("partidos").select("id, cerrado").eq("fecha_ronda", ronda)
                      .eq("anulado", False).execute().data)
    ids_ronda = [p["id"] for p in partidos_ronda]
    total_fecha = len(ids_ronda)  # total real de partidos de la fecha — solo para mostrar en pantalla
    ids_abiertos = {p["id"] for p in partidos_ronda if not p["cerrado"]}
    n_abiertos = len(ids_abiertos)
    jugadores = db().table("jugadores").select("id, nombre").order("nombre").execute().data
    preds = (db().table("predicciones").select("jugador_id, partido_id")
             .in_("partido_id", ids_ronda).execute().data if ids_ronda else [])
    contadas = {}
    contadas_cerrados = {}
    for pr in preds:
        contadas[pr["jugador_id"]] = contadas.get(pr["jugador_id"], 0) + 1
        if pr["partido_id"] not in ids_abiertos:
            contadas_cerrados[pr["jugador_id"]] = contadas_cerrados.get(pr["jugador_id"], 0) + 1
    return [{"id": j["id"], "nombre": j["nombre"], "n": contadas.get(j["id"], 0),
              "total": n_abiertos + contadas_cerrados.get(j["id"], 0), "total_fecha": total_fecha,
              "fecha_cerrada": n_abiertos == 0}
            for j in jugadores]


def fecha_totalmente_predicha(estado_jugadores) -> bool:
    """True si TODOS los jugadores completaron lo que alcanzaron a predecir
    de la fecha (ver calcular_estado_prediccion)."""
    return bool(estado_jugadores) and all(e["total"] > 0 and e["n"] >= e["total"] for e in estado_jugadores)


def fecha_ya_revelada(ronda) -> bool:
    """True si esta fecha ya se reveló alguna vez (candado persistido en
    notificaciones_enviadas) — a diferencia de fecha_totalmente_predicha(),
    que se recalcula en vivo y puede volver a False si luego se anula una
    predicción individual (ej. una tardía). Una vez revelada, se queda
    revelada: ya se mostraron las apuestas de todos, así que no debe
    reabrirse la edición aunque el conteo ya no dé "100% completo"."""
    return bool(db().table("notificaciones_enviadas").select("id")
                .eq("fecha_ronda", ronda).eq("tipo", "todos_predijeron").execute().data)


def intentar_notificar_todos_predijeron(ronda):
    """Si la fecha se acaba de completar (todos predijeron), manda el correo
    de revelación a los 10 — una sola vez por fecha. El insert en
    notificaciones_enviadas (unique fecha_ronda+tipo) actúa como candado:
    si dos jugadores completan casi al mismo tiempo, solo el primer insert
    exitoso dispara el envío; el segundo choca con la unique constraint y
    no reenvía."""
    try:
        db().table("notificaciones_enviadas").insert(
            {"fecha_ronda": ronda, "tipo": "todos_predijeron"}).execute()
    except Exception:
        return  # ya se envió (o falló el insert por otra razón) — no reintentar

    partidos_ronda = (db().table("partidos").select("id, local, visita")
                       .eq("fecha_ronda", ronda).eq("anulado", False).order("kickoff").execute().data)
    ids_ronda = [p["id"] for p in partidos_ronda]
    todas = (db().table("v_puntos")
             .select("partido_id, jugador_id, gl_pred, gv_pred, es_exacto")
             .in_("partido_id", ids_ronda).execute().data)
    jugadores = db().table("jugadores").select("id, nombre, email").execute().data
    cuerpo = build_reveal_matches(partidos_ronda, jugadores, todas)
    for jugador in jugadores:
        if jugador["email"]:
            enqueue_all_predicted(db(), jugador["email"], jugador["id"], ronda, cuerpo)


def get_secret(name):
    value = os.environ.get(name)
    if not value:
        try:
            value = st.secrets[name]
        except (KeyError, FileNotFoundError):
            value = None
    return value


def get_session_secret():
    secret = get_secret("SESSION_SECRET")
    if not secret:
        raise RuntimeError("Falta configurar SESSION_SECRET en el servidor.")
    return secret


def crear_sesion_jugador(player):
    token = sign_session(player["id"], player["session_version"],
                         int(time.time()) + DIAS_SESION * 86400, get_session_secret())
    cookies().set(COOKIE_SESION, token, max_age=DIAS_SESION * 86400,
                  same_site="strict")
    st.session_state["sesion_token"] = token
    st.session_state["jugador_id"] = player["id"]
    st.session_state["jugador_nombre"] = player["nombre"]
    st.session_state.pop("es_admin", None)


def limpiar_sesion():
    for key in ("sesion_token", "jugador_id", "jugador_nombre", "es_admin"):
        st.session_state.pop(key, None)


def login():
    with st.container(border=True, key="card_login"):
        st.markdown(
            f'<div style="text-align:center">{logo(LIGA_ID, 100)}</div>',
            unsafe_allow_html=True)
        st.title("Polla Liga Pro Ecuador")
        jugadores = leer_jugadores()
        if not jugadores:
            st.error("Aún no hay jugadores registrados. Pídele al admin que te agregue.")
            st.stop()
        nombres = [j["nombre"] for j in jugadores]
        nombre = st.selectbox("¿Quién eres?", nombres)
        pin = st.text_input("PIN", type="password", max_chars=4)
        if st.button("Entrar", type="primary"):
            get_session_secret()
            fila = autenticar_jugador(db(), nombre, pin)
            if fila:
                crear_sesion_jugador(fila)
                # El componente de cookies escribe en el navegador de forma
                # asíncrona (vía su iframe interno) — sin esta pausa, el
                # rerun cortaba el ciclo antes de que la cookie llegara a
                # existir y la sesión nunca sobrevivía a un refresco.
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(ERROR_ACCESO)

    st.markdown(
        f'<div style="text-align:center; color:var(--polla-muted); font-size:0.75em; margin-top:1rem">'
        f'© {datetime.now().year} Vicente Macas Espinosa</div>',
        unsafe_allow_html=True)


def cargar_partidos_abiertos():
    """Partidos que el jugador aún puede predecir. Se confía únicamente en
    la columna `cerrado` (actualizada por cerrar_por_kickoff() en sync) —
    NO se filtra además por kickoff > ahora, porque bajo la política de
    plazo (1° y 2° partido cierran a su hora; 3° en adelante quedan
    abiertos hasta el kickoff del 2°) puede haber partidos con kickoff ya
    pasado que siguen legítimamente abiertos."""
    return (db().table("partidos").select("*")
            .gt("cierre_predicciones", datetime.now(timezone.utc).isoformat())
            .order("kickoff").execute().data)


def cargar_predicciones(jugador_id):
    filas = db().table("predicciones").select("*").eq("jugador_id", jugador_id).execute().data
    return {f["partido_id"]: f for f in filas}


def tarjeta_partido(p, mis_pred):
    """Una línea por equipo: escudo, nombre y su marcador en la misma fila
    (st.container(horizontal=True) sí se mantiene horizontal en el celular,
    a diferencia de st.columns). Arranca en 0 y no vacío: con value=None
    Streamlit 1.60 desactiva los botones +/- (comprobado). El 0-0 sin tocar
    se ataja en el resumen de confirmar_pronosticos()."""
    existente = mis_pred.get(p["id"])
    with st.container(border=True, key=f"card_partido_{p['id']}"):
        st.markdown(
            f'<div class="polla-fila-cabecera"><span class="polla-fila-hora">'
            f'{dia_hora_local(p["kickoff"])}</span>{badge_cuenta_regresiva(p["cierre_predicciones"])}</div>',
            unsafe_allow_html=True)
        goles = []
        for lado, sufijo in (("local", "gl"), ("visita", "gv")):
            with st.container(horizontal=True, vertical_alignment="center", gap="small",
                              key=f"fila_{sufijo}_{p['id']}"):
                st.markdown(
                    f'<div class="polla-fila-equipo">{logo(p.get(f"{lado}_id"), 28)}'
                    f'<span>{escape(str(p[lado]))}</span></div>',
                    unsafe_allow_html=True, width="stretch")
                goles.append(st.number_input(
                    f"Goles de {p[lado]}", min_value=0, max_value=15, step=1,
                    value=existente[f"{sufijo}_pred"] if existente else 0,
                    key=f"{'saved_' if existente else ''}{sufijo}_{p['id']}",
                    label_visibility="collapsed", disabled=existente is not None, width=136))
        if existente:
            st.caption("🔒 Pronóstico guardado y definitivo.")
    return goles[0], goles[1]


@st.fragment(run_every=60)
def linea_progreso(ronda, partidos_ronda, n_faltantes):
    """Progreso de la fecha y próximo cierre. Es un fragmento que se
    refresca solo cada minuto: la cuenta regresiva avanza sin recargar y
    sin volver a ejecutar el formulario."""
    abiertos = [p for p in partidos_ronda
                if pd.to_datetime(p["cierre_predicciones"]) > datetime.now(timezone.utc)]
    proximo = min((p["cierre_predicciones"] for p in abiertos), default=None)
    listos = len(partidos_ronda) - n_faltantes
    clase = "polla-progreso polla-progreso--ok" if n_faltantes == 0 else "polla-progreso"
    cierre = f" · próximo cierre {badge_cuenta_regresiva(proximo)}" if proximo else ""
    st.markdown(
        f'<div class="{clase}"><b>Fecha {ronda}</b> · {listos} de {len(partidos_ronda)} '
        f'pronosticados{cierre}</div>',
        unsafe_allow_html=True)


@st.dialog("Confirma tus pronósticos")
def confirmar_pronosticos(ronda_sel, listos, partidos_ronda):
    """Resumen antes de guardar: al confirmar quedan definitivos. Los 0-0
    se marcan porque es el valor inicial: puede ser un partido sin tocar."""
    por_id = {p["id"]: p for p in partidos_ronda}
    n_ceros = 0
    for partido_id, (gl, gv) in listos.items():
        p = por_id[partido_id]
        cero = int(gl) == 0 and int(gv) == 0
        n_ceros += cero
        clase = "polla-confirmar-fila polla-confirmar-fila--cero" if cero else "polla-confirmar-fila"
        st.markdown(
            f'<div class="{clase}"><span>{escape(str(p["local"]))}</span>'
            f'<b>{int(gl)} – {int(gv)}</b><span>{escape(str(p["visita"]))}</span></div>',
            unsafe_allow_html=True)
    if n_ceros:
        st.warning(f"Revisa {'el 0-0 marcado' if n_ceros == 1 else f'los {n_ceros} 0-0 marcados'}: "
                   "¿de verdad es tu pronóstico o te faltó cambiarlo?")
    st.caption("Al guardar quedan definitivos: no se podrán cambiar.")
    c1, c2 = st.columns(2)
    if c1.button("Volver a editar", width="stretch"):
        st.rerun()
    if c2.button("Sí, guardar", type="primary", width="stretch"):
        guardar_pronosticos(ronda_sel, listos)
        st.rerun()


def guardar_pronosticos(ronda_sel, valores):
    # La RPC de Postgres decide con su propio reloj si el plazo sigue
    # abierto, aunque el formulario se haya cargado antes o el sync
    # todavía no haya actualizado `cerrado`.
    jugador_id = st.session_state["jugador_id"]
    ids = list(valores.keys())
    frescos = {p["id"]: p for p in db().table("partidos").select("id, local, visita")
               .in_("id", ids).execute().data}
    guardados, rechazados = 0, []
    confirmadas = []
    for partido_id, (gl, gv) in valores.items():
        p = frescos.get(partido_id)
        if not p:
            rechazados.append(p["local"] + " vs " + p["visita"] if p else f"partido {partido_id}")
            continue
        try:
            save_prediction(db(), jugador_id, partido_id, gl, gv)
        except Exception as error:
            if any(motivo in str(error).lower()
                   for motivo in ("plazo cerrado", "prediccion ya guardada", "prediccion definitiva")):
                rechazados.append(p["local"] + " vs " + p["visita"])
                continue
            raise
        guardados += 1
        confirmadas.append({"local": p["local"], "visita": p["visita"], "gl": int(gl), "gv": int(gv)})

    if confirmadas:
        jugador = db().table("jugadores").select("email").eq("id", jugador_id).single().execute().data
        if jugador and jugador.get("email"):
            enqueue_confirmation(
                db(), jugador["email"], st.session_state["jugador_nombre"], ronda_sel,
                confirmadas, player_id=jugador_id)
        # Revelación: sale ya si con este guardado todos completaron la
        # fecha; si no, el sync la manda al kickoff del 2° partido (y
        # también la cubre si este disparo no alcanzara a encolarse).
        if fecha_totalmente_predicha(calcular_estado_prediccion(ronda_sel)):
            intentar_notificar_todos_predijeron(ronda_sel)

    st.session_state["mensaje_guardado"] = (guardados, rechazados)


def vista_predicciones():
    jugador_id = st.session_state["jugador_id"]
    st.markdown(
        f'<div class="polla-saludo">{logo(LIGA_ID, 40)}'
        f'<span>Hola, <b>{escape(st.session_state["jugador_nombre"])}</b> 👋</span></div>',
        unsafe_allow_html=True)

    # Mensaje persistente: el st.success de más abajo se mostraba un instante
    # antes del st.rerun() y desaparecía sin que el usuario lo notara, dejando
    # la sensación de que "no pasó nada" al guardar. Se guarda en
    # session_state para que sobreviva al rerun y se vea arriba de la página.
    if "mensaje_guardado" in st.session_state:
        guardados, rechazados = st.session_state.pop("mensaje_guardado")
        if guardados:
            st.success(f"✅ ¡{guardados} predicciones guardadas correctamente!")
        if rechazados:
            st.error("⚠️ No se guardaron (plazo cerrado o pronóstico ya guardado): " + ", ".join(rechazados))

    partidos = cargar_partidos_abiertos()
    if not partidos:
        st.info("No hay partidos abiertos para predecir por ahora. Vuelve pronto.")
        return

    mis_pred = cargar_predicciones(jugador_id)
    rondas = sorted({p["fecha_ronda"] for p in partidos}, key=lambda r: (r is None, r))
    if len(rondas) > 1:
        ronda_sel = selector_fecha(rondas, key="ronda_pred")
    else:
        ronda_sel = rondas[0]
    partidos_ronda = [p for p in partidos if p["fecha_ronda"] == ronda_sel]
    faltantes = [p for p in partidos_ronda if p["id"] not in mis_pred]

    linea_progreso(ronda_sel, partidos_ronda, len(faltantes))
    with st.expander("¿Cómo se puntúa?"):
        st.caption("Marcador exacto: 1 pt por Exacto + 1 pt por G/E/P (2 pts total); "
                   "G/E/P no exacto: 1 pt; fallo: 0. Los pronósticos guardados son "
                   "definitivos.")

    # La revelación sigue impidiendo nuevas jugadas para una fecha ya visible.
    # Cada pronóstico guardado es definitivo, aunque la fecha aún no se revele.
    if fecha_ya_revelada(ronda_sel):
        st.info("🔒 Todos ya predijeron esta fecha — las predicciones quedaron congeladas. "
                "Ve a 'Mis jugadas' para verlas todas.")
        return

    with st.form("form_predicciones"):
        valores = {}
        for p in partidos_ronda:
            gl, gv = tarjeta_partido(p, mis_pred)
            if p["id"] not in mis_pred:
                valores[p["id"]] = (gl, gv)
        enviado = st.form_submit_button("Revisar y guardar", type="primary",
                                       disabled=not faltantes, width="stretch")

    if enviado and valores:
        confirmar_pronosticos(ronda_sel, valores, partidos_ronda)


def fila_estado_jugador(nombre, n, total_fecha, completo, es_yo, fecha_cerrada=False):
    """n/total_fecha es el conteo REAL mostrado en pantalla (ej. 6/8 si un
    jugador entró tarde y ya no alcanzó a predecir un partido cerrado).
    `completo` decide el ícono ✅ y viene de fecha_totalmente_predicha() —
    considera "completo" a quien predijo todo lo que alcanzó a ver, aunque
    eso sea menos que total_fecha (ver calcular_estado_prediccion). Si no
    completó: ⏳ mientras quede algún partido abierto, ❌ cuando ya no puede
    predecir nada más."""
    icono = "✅" if completo else ("❌" if fecha_cerrada else "⏳")
    clase = "polla-rank-row polla-rank-row--yo" if es_yo else "polla-rank-row"
    st.markdown(
        f'<div class="{clase}">'
        f'<span style="flex:1; font-weight:{"700" if es_yo else "500"}">{nombre}</span>'
        f'<span style="font-size:1.1em">{icono}</span>'
        f'<span style="font-size:0.85em; color:var(--polla-muted); margin-left:4px;">({n}/{total_fecha})</span>'
        f'</div>',
        unsafe_allow_html=True)


def clasificar_resultado(gl, gv) -> str:
    """'local' | 'empate' | 'visita' según los goles."""
    if gl > gv:
        return "local"
    if gl < gv:
        return "visita"
    return "empate"


def barra_reparto(n_local, n_empate, n_visita) -> str:
    """Barra proporcional de a qué le fueron los 10 (no es semántica de
    acierto/fallo — son 3 tintes del acento, distinto de las píldoras de
    puntaje que sí usan verde/ámbar/rosa para exacto/1X2/fallo)."""
    total = n_local + n_empate + n_visita
    if total == 0:
        return ""

    def pct(n):
        return round(100 * n / total)

    return (
        '<div style="display:flex; height:8px; border-radius:999px; overflow:hidden; '
        'background:var(--polla-border); margin-bottom:10px;">'
        f'<div style="width:{pct(n_local)}%; background:var(--polla-accent);"></div>'
        f'<div style="width:{pct(n_empate)}%; background:#A9BDB0;"></div>'
        f'<div style="width:{pct(n_visita)}%; background:#D8D4C8;"></div>'
        '</div>'
    )


def fila_pronostico_grupo(nombre, gl_pred, gv_pred, es_exacto, es_yo):
    """Fila dentro de una columna de grupo (local/empate/visita). No repite
    la píldora de puntaje en cada fila — el grupo ya dice si acertaron el
    resultado; solo se resalta quién, dentro del grupo, clavó el marcador
    exacto."""
    fondo = "background:var(--polla-exacto);" if es_exacto else ""
    borde = "border-left:4px solid var(--polla-accent);" if es_yo else ""
    peso = "700" if es_yo else "500"
    check = (
        '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#3E6A56" '
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" '
        'style="flex-shrink:0"><path d="M20 6 9 17l-5-5"/></svg>'
    ) if es_exacto else ""
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:6px; padding:6px 8px; '
        f'border-radius:6px; margin-bottom:2px; {fondo} {borde}">'
        f'<span style="flex:1; font-size:13px; font-weight:{peso};">{nombre}</span>'
        f'{check}'
        f'<span style="font-variant-numeric:tabular-nums; font-weight:700; font-size:13px;">'
        f'{gl_pred}-{gv_pred}</span>'
        f'</div>',
        unsafe_allow_html=True)


def vista_ranking():
    st.subheader("🏆 Ranking")

    jugadores = leer_jugadores()
    partidos = leer_rondas_partidos()
    if not partidos:
        st.info("Todavía no hay partidos cargados.")
        return

    rondas = sorted({p["fecha_ronda"] for p in partidos if p["fecha_ronda"] is not None})
    pollas = sorted({numero_polla(r) for r in rondas})
    opciones = [f"Polla {n} (Fechas {rango_polla(n)[0]}-{rango_polla(n)[1]})" for n in pollas]
    idx = st.selectbox("Selecciona la polla", range(len(pollas)),
                        index=len(pollas) - 1, format_func=lambda i: opciones[i], key="polla_ranking")
    polla_sel = pollas[idx]
    ini, fin = rango_polla(polla_sel)

    ids_partidos = [p["id"] for p in partidos if p["fecha_ronda"] is not None and ini <= p["fecha_ronda"] <= fin]
    # partido_id -> fecha_ronda, para poder desglosar puntos por fecha además
    # de por polla completa (usado en las pestañas "Por fecha" y "Barras").
    ronda_por_partido = {p["id"]: p["fecha_ronda"] for p in partidos}
    fechas_polla = list(range(ini, fin + 1))

    puntos_filas = leer_puntos_partidos(tuple(sorted(ids_partidos)))

    agregados = {}
    por_fecha = {}  # jugador_id -> {fecha_ronda: puntos}
    for f in puntos_filas:
        jid = f["jugador_id"]
        acc = agregados.setdefault(
            jid, {"puntos_totales": 0, "aciertos_exactos": 0, "aciertos_1x2": 0, "partidos_predichos": 0})
        acc = add_score_to_ranking(acc, points=f["puntos"], exact=f["es_exacto"])
        agregados[jid] = acc
        acc["partidos_predichos"] += 1
        fecha = ronda_por_partido.get(f["partido_id"])
        if fecha is not None:
            por_fecha.setdefault(jid, {})[fecha] = por_fecha.setdefault(jid, {}).get(fecha, 0) + f["puntos"]

    ranking = []
    for j in jugadores:
        acc = agregados.get(
            j["id"], {"puntos_totales": 0, "aciertos_exactos": 0, "aciertos_1x2": 0, "partidos_predichos": 0})
        ranking.append({"jugador_id": j["id"], "nombre": j["nombre"], **acc})
    ranking.sort(key=lambda r: (-r["puntos_totales"], -r["aciertos_exactos"]))

    mi_id = st.session_state.get("jugador_id")
    medallas = {1: "🥇", 2: "🥈", 3: "🥉"}
    COL_EXACTO = "Exacto"
    COL_1X2 = "G/E/P"

    filas_tabla = []
    for i, fila in enumerate(ranking, start=1):
        nombre = fila["nombre"] + (" 👤" if fila["jugador_id"] == mi_id else "")
        filas_tabla.append({
            "Puesto": medallas.get(i, f"#{i}"),
            "Jugador": nombre,
            "Ptos": fila["puntos_totales"],
            COL_EXACTO: fila["aciertos_exactos"],
            COL_1X2: fila["aciertos_1x2"],
        })
    dfr = pd.DataFrame(filas_tabla)
    st.dataframe(
        dfr, width="stretch", hide_index=True,
        column_config={
            "Puesto": st.column_config.TextColumn(width="small"),
            "Jugador": st.column_config.TextColumn(width="medium"),
            "Ptos": st.column_config.NumberColumn(width="small"),
            COL_EXACTO: st.column_config.NumberColumn(
                width="small", help="Puntos por marcador exacto (1 por acierto)"),
            COL_1X2: st.column_config.NumberColumn(
                width="small", help="Puntos por G/E/P (1 por acierto)"),
        })

    st.markdown("#### Puntos por fecha")
    filas_fecha = []
    for i, fila in enumerate(ranking, start=1):
        nombre = fila["nombre"] + (" 👤" if fila["jugador_id"] == mi_id else "")
        puntos_jugador = por_fecha.get(fila["jugador_id"], {})
        filas_fecha.append({
            "Puesto": medallas.get(i, f"#{i}"),
            "Jugador": nombre,
            **{f"F{r}": puntos_jugador.get(r, 0) for r in fechas_polla},
            "Total": fila["puntos_totales"],
        })
    dff = pd.DataFrame(filas_fecha)
    col_config = {
        "Puesto": st.column_config.TextColumn(width="small"),
        "Jugador": st.column_config.TextColumn(width="medium"),
        "Total": st.column_config.NumberColumn(width="small"),
    }
    for r in fechas_polla:
        col_config[f"F{r}"] = st.column_config.NumberColumn(width="small")
    st.dataframe(dff, width="stretch", hide_index=True, column_config=col_config)
    st.caption("Columnas en 0 = fecha aún sin jugar o sin puntos en esa fecha.")

    st.markdown("#### Puntos por fecha — barras")
    colores = ["#9DB8A8", "#E4C580", "#D8A9A0", "#A8B8D8", "#C9A8CC"]
    max_total = max((r["puntos_totales"] for r in ranking), default=0)
    for i, fila in enumerate(ranking, start=1):
        nombre = fila["nombre"] + (" 👤" if fila["jugador_id"] == mi_id else "")
        puntos_jugador = por_fecha.get(fila["jugador_id"], {})
        segmentos_html = "".join(
            f'<div style="height:100%; background:{colores[idx % len(colores)]}; '
            f'width:{(puntos_jugador.get(r, 0) / max_total * 100) if max_total else 0}%;"></div>'
            for idx, r in enumerate(fechas_polla)
        )
        st.markdown(
            f'<div style="display:grid; grid-template-columns:140px 1fr 32px; align-items:center; '
            f'gap:10px; margin-bottom:10px;">'
            f'<div style="font-size:0.82rem; font-weight:600; white-space:nowrap; overflow:hidden; '
            f'text-overflow:ellipsis;">{medallas.get(i, f"#{i}")} {nombre}</div>'
            f'<div style="height:16px; border-radius:4px; overflow:hidden; display:flex; '
            f'background:#EFEFEA;">{segmentos_html}</div>'
            f'<div style="text-align:right; font-size:0.86rem; font-weight:800;">{fila["puntos_totales"]}</div>'
            f'</div>',
            unsafe_allow_html=True)
    leyenda_html = "".join(
        f'<div style="display:flex; align-items:center; gap:6px; font-size:0.74rem; color:var(--polla-muted);">'
        f'<span style="width:10px; height:10px; border-radius:2px; background:{colores[idx % len(colores)]}; '
        f'display:inline-block;"></span>Fecha {r}</div>'
        for idx, r in enumerate(fechas_polla)
    )
    st.markdown(
        f'<div style="display:flex; gap:16px; flex-wrap:wrap; padding-top:10px; '
        f'border-top:1px solid var(--polla-border); margin-top:6px;">{leyenda_html}</div>',
        unsafe_allow_html=True)


def vista_resultados():
    st.subheader("📋 Últimos resultados")
    cerrados = leer_resultados_recientes()
    if not cerrados:
        st.info("Aún no hay resultados cargados.")
        return

    rondas = sorted({p["fecha_ronda"] for p in cerrados}, key=lambda r: (r is None, r), reverse=True)
    ronda_sel = selector_fecha(rondas, key="ronda_res")
    partidos_ronda = sorted(
        (p for p in cerrados if p["fecha_ronda"] == ronda_sel), key=lambda p: p["kickoff"])

    for i, p in enumerate(partidos_ronda, start=1):
        with st.container(border=True, key=f"card_resultado_{p['id']}"):
            kickoff_local = a_local(p["kickoff"]).strftime("%d/%m")
            st.caption(f"Partido {i} — {kickoff_local}")
            st.markdown(
                render_resultado(
                    p["local"], logo(p.get("local_id"), 24), p["gl_real"],
                    p["gv_real"], p["visita"], logo(p.get("visita_id"), 24),
                ),
                unsafe_allow_html=True,
            )


def vista_mis_predicciones():
    jugador_id = st.session_state["jugador_id"]
    st.subheader("📝 Mis predicciones")

    # El selector de fecha se basa en TODOS los partidos cargados, no solo
    # en los que el jugador actual ya predijo — si no, alguien que aún no
    # predice nada en una fecha ni siquiera podría seleccionarla para ver
    # el checklist de quién sí lo hizo.
    partidos_todos = leer_rondas_partidos()
    rondas = sorted({p["fecha_ronda"] for p in partidos_todos if p["fecha_ronda"] is not None}, reverse=True)
    if not rondas:
        st.info("Todavía no hay partidos cargados.")
        return

    # Por defecto, la fecha "actual" es la más próxima que todavía tiene
    # partidos sin cerrar (la que se está jugando/por jugar) — no la más
    # alta cargada, que puede ser una fecha futura recién subida al fixture.
    rondas_abiertas = sorted({p["fecha_ronda"] for p in partidos_todos
                               if p["fecha_ronda"] is not None and not p["cerrado"]})
    ronda_actual = rondas_abiertas[0] if rondas_abiertas else rondas[0]
    ronda_sel = selector_fecha(rondas, key="ronda_mis_pred", ronda_defecto=ronda_actual)

    # Checklist de quién ya predijo esta fecha: solo el estado (✅/⏳), nunca
    # el marcador que cada quien puso — eso arruinaría la apuesta antes de
    # que cierren los partidos.
    st.markdown("#### Quién ya predijo esta fecha")
    estado_jugadores = calcular_estado_prediccion(ronda_sel)
    for e in estado_jugadores:
        completo = e["total"] > 0 and e["n"] >= e["total"]
        fila_estado_jugador(e["nombre"], e["n"], e["total_fecha"], completo, e["id"] == jugador_id,
                            e["fecha_cerrada"])

    # Revelación: recién cuando LOS 10 terminaron de predecir TODA la fecha
    # se muestra qué puso cada quien en cada partido. Antes de eso nadie ve
    # nada — ver esto y luego editar la propia predicción sería copiarse.
    # Se usa el candado persistido (fecha_ya_revelada), no el recálculo en
    # vivo: si luego se anula una predicción individual, la fecha sigue
    # mostrándose revelada — ya se mostró una vez, no debe desaparecer.
    if fecha_ya_revelada(ronda_sel):
        st.markdown("#### 🔓 Predicciones de todos — fecha completa")
        partidos_ronda_full = (db().table("partidos")
                                .select("id, local, visita, kickoff, gl_real, gv_real")
                                .eq("fecha_ronda", ronda_sel).eq("anulado", False)
                                .order("kickoff").execute().data)
        ids_ronda = [p["id"] for p in partidos_ronda_full]
        todas = (db().table("v_puntos")
                 .select("jugador_id, partido_id, gl_pred, gv_pred, es_exacto, jugadores(nombre)")
                 .in_("partido_id", ids_ronda).execute().data)
        por_partido = {}
        for f in todas:
            por_partido.setdefault(f["partido_id"], []).append(f)

        for i, p in enumerate(partidos_ronda_full, start=1):
            preds_partido = por_partido.get(p["id"], [])
            grupos = {"local": [], "empate": [], "visita": []}
            for f in preds_partido:
                grupos[clasificar_resultado(f["gl_pred"], f["gv_pred"])].append(f)
            for g in grupos.values():
                g.sort(key=lambda f: f["jugadores"]["nombre"])

            hay_resultado = p["gl_real"] is not None and p["gv_real"] is not None
            resultado_real = clasificar_resultado(p["gl_real"], p["gv_real"]) if hay_resultado else None
            etiquetas = {"local": p["local"], "empate": "Empate", "visita": p["visita"]}

            with st.expander(f"Partido {i}: {p['local']} vs {p['visita']}"):
                if hay_resultado:
                    st.caption(f"Resultado real: {p['gl_real']}-{p['gv_real']}")
                st.markdown(
                    barra_reparto(len(grupos["local"]), len(grupos["empate"]), len(grupos["visita"])),
                    unsafe_allow_html=True)

                cols = st.columns(3)
                for col, tipo in zip(cols, ["local", "empate", "visita"]):
                    with col:
                        es_correcto = hay_resultado and tipo == resultado_real
                        key = f"grupo_{'correcto' if es_correcto else 'otro'}_{p['id']}_{tipo}"
                        with st.container(border=True, key=key):
                            check = (
                                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
                                'stroke="#3E6A56" stroke-width="2.5" stroke-linecap="round" '
                                'stroke-linejoin="round" style="vertical-align:-2px; margin-right:4px">'
                                '<path d="M20 6 9 17l-5-5"/></svg>'
                            ) if es_correcto else ""
                            color_txt = "color:var(--polla-accent);" if es_correcto else "color:var(--polla-muted);"
                            st.markdown(
                                f'<div style="{color_txt} font-weight:700; font-size:12.5px; '
                                f'margin-bottom:2px;">{check}{etiquetas[tipo]}</div>'
                                f'<div style="font-size:20px; font-weight:800; {color_txt} '
                                f'margin-bottom:8px;">{len(grupos[tipo])}</div>',
                                unsafe_allow_html=True)
                            if not grupos[tipo]:
                                st.caption("Nadie")
                            for f in grupos[tipo]:
                                fila_pronostico_grupo(
                                    f["jugadores"]["nombre"], f["gl_pred"], f["gv_pred"],
                                    bool(f["es_exacto"]), f["jugador_id"] == jugador_id)

    st.markdown("#### Mis predicciones de esta fecha")
    filas = (db().table("v_puntos").select("*, partidos(local, visita, kickoff, fecha_ronda, anulado)")
             .eq("jugador_id", jugador_id).execute().data)
    de_la_ronda = sorted(
        (f for f in filas
         if f["partidos"]["fecha_ronda"] == ronda_sel and not f["partidos"]["anulado"]),
        key=lambda f: f["partidos"]["kickoff"])
    if not de_la_ronda:
        st.info("Todavía no has predicho ningún partido de esta fecha.")
        return

    jugados = [f for f in de_la_ronda if f["puntos"] is not None]
    if jugados:
        st.metric("Puntos en esta fecha", sum(f["puntos"] for f in jugados))

    for f in de_la_ronda:
        pa = f["partidos"]
        with st.container(border=True, key=f"card_mipred_{f['prediccion_id']}"):
            kickoff_local = a_local(pa["kickoff"]).strftime("%d/%m %H:%M")
            c1, c2 = st.columns([4, 1])
            with c1:
                if f["puntos"] is not None:
                    detalle = f"real {f['gl_real']}-{f['gv_real']} · {kickoff_local}"
                else:
                    detalle = f"pendiente · {kickoff_local}"
                st.markdown(
                    f"**{pa['local']} {f['gl_pred']}-{f['gv_pred']} {pa['visita']}**  \n"
                    f"<span style='color:var(--polla-muted); font-size:0.85em'>{detalle}</span>",
                    unsafe_allow_html=True)
            with c2:
                st.markdown(pill_puntos(f["puntos"], f["es_exacto"]), unsafe_allow_html=True)


def vista_admin():
    st.subheader("🛠️ Panel de Administrador")

    jugadores = db().table("jugadores").select("id, nombre, email").order("nombre").execute().data
    partidos = db().table("partidos").select("*").order("kickoff").execute().data

    if not partidos:
        st.info("Todavía no hay partidos cargados.")
        return

    abiertos = [p for p in partidos if not p["cerrado"]]
    con_resultado = [p for p in partidos if p["gl_real"] is not None]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Jugadores", len(jugadores))
    c2.metric("Partidos cargados", len(partidos))
    c3.metric("Abiertos", len(abiertos))
    c4.metric("Con resultado", len(con_resultado))

    proximos = sorted((p for p in abiertos if pd.to_datetime(p["kickoff"]) > datetime.now(timezone.utc)),
                       key=lambda p: p["kickoff"])
    if proximos:
        p = proximos[0]
        st.markdown(
            f"⏱️ **Próximo cierre:** {p['local']} vs {p['visita']} — "
            f"{dia_hora_local(p['kickoff'])} {badge_cuenta_regresiva(p['kickoff'])}",
            unsafe_allow_html=True)

    rondas = sorted({p["fecha_ronda"] for p in partidos if p["fecha_ronda"] is not None}, reverse=True)
    ronda_sel = selector_fecha(rondas, key="ronda_admin")
    partidos_ronda = sorted(
        (p for p in partidos if p["fecha_ronda"] == ronda_sel), key=lambda p: p["kickoff"])

    st.markdown("#### Partidos de la fecha")
    tabla_partidos = pd.DataFrame([{
        "Partido": f"{p['local']} vs {p['visita']}",
        "Hora (Ecuador)": dia_hora_local(p["kickoff"]),
        "Estado": "Cerrado" if p["cerrado"] else "Abierto",
        "Resultado": f"{p['gl_real']}-{p['gv_real']}" if p["gl_real"] is not None else "—",
    } for p in partidos_ronda])
    st.dataframe(tabla_partidos, width="stretch", hide_index=True)

    st.markdown("#### Quién ya predijo esta fecha")
    filas_check = []
    for e in calcular_estado_prediccion(ronda_sel):
        if e["n"] == 0:
            estado = "❌ Nada"
        elif e["n"] < e["total"]:
            estado = f"⚠️ Parcial ({e['n']}/{e['total']})"
        else:
            estado = "✅ Completo"
        filas_check.append({"Jugador": e["nombre"], "Predicciones": f"{e['n']}/{e['total']}", "Estado": estado})
    st.dataframe(pd.DataFrame(filas_check), width="stretch", hide_index=True)

    st.markdown("#### Lista de jugadores")
    st.dataframe(pd.DataFrame([{"Jugador": j["nombre"], "Correo": j["email"] or ""} for j in jugadores]),
                 width="stretch", hide_index=True)

    st.markdown("#### Correos para confirmación de predicciones")
    st.caption("Deja vacío el correo de quien no quiera recibir confirmación por email.")
    df_emails = pd.DataFrame([{"id": j["id"], "Jugador": j["nombre"], "Email": j["email"] or ""}
                               for j in jugadores])
    editado = st.data_editor(
        df_emails, width="stretch", hide_index=True, key="editor_emails",
        column_config={"id": None, "Jugador": st.column_config.TextColumn(disabled=True)})
    if st.button("Guardar correos"):
        for _, fila in editado.iterrows():
            db().table("jugadores").update({"email": fila["Email"].strip() or None}).eq("id", fila["id"]).execute()
        st.success("Correos actualizados.")
        st.rerun()


def restaurar_sesion_desde_cookie():
    """Restore only a signed, unexpired token with a current database version."""
    try:
        token = cookies().get(COOKIE_SESION)
    except TypeError:
        # El componente de cookies aún no resolvió su valor real en este
        # rerun (queda None en vez de {} de forma transitoria) — se
        # intenta de nuevo en el siguiente rerun natural de Streamlit.
        return
    if not token:
        return
    fila = jugador_de_sesion(db(), token, get_session_secret(), int(time.time()))
    if fila:
        st.session_state["sesion_token"] = token
        st.session_state["jugador_id"] = fila["id"]
        st.session_state["jugador_nombre"] = fila["nombre"]
        st.session_state.pop("es_admin", None)
    else:
        limpiar_sesion()
        cookies().remove(COOKIE_SESION)


def main():
    token = st.session_state.get("sesion_token")
    if token:
        # Revalidate active tabs as well as browser refreshes after PIN revocation.
        if not jugador_de_sesion(db(), token, get_session_secret(), int(time.time())):
            limpiar_sesion()
            cookies().remove(COOKIE_SESION)
    else:
        limpiar_sesion()
        restaurar_sesion_desde_cookie()
    if "jugador_id" not in st.session_state:
        login()
        return
    app_autenticada()


def app_autenticada():
    """Todo lo que ve un jugador ya autenticado (main() decide si lo está)."""
    es_admin = st.session_state.get("es_admin", False)
    # Navegación con un solo widget: a diferencia de st.tabs (que ejecuta las
    # 4 vistas y todas sus consultas en cada clic), solo se dibuja la vista
    # elegida. key="nav" genera la clase pública .st-key-nav que usa el CSS
    # de la barra inferior en móvil.
    vistas = {
        "Predecir": (":material/sports_soccer:", vista_predicciones),
        "Ranking": (":material/leaderboard:", vista_ranking),
        "Resultados": (":material/sports_score:", vista_resultados),
        "Mis jugadas": (":material/edit_note:", vista_mis_predicciones),
        "Perfil": (":material/person:", vista_perfil),
    }
    if es_admin:
        vistas["Admin"] = (":material/admin_panel_settings:", vista_admin)
    if st.session_state.get("nav") not in vistas:
        st.session_state["nav"] = "Predecir"
    eleccion = st.segmented_control(
        "Navegación", list(vistas), key="nav", required=True,
        format_func=lambda v: f"{vistas[v][0]} {v}", label_visibility="collapsed",
        width="stretch")
    vistas[eleccion or "Predecir"][1]()


def vista_perfil():
    """Sesión, PIN y acceso de administrador. Antes vivían en la barra
    lateral, que en el celular queda escondida detrás del menú."""
    es_admin = st.session_state.get("es_admin", False)
    st.subheader("👤 Perfil")
    st.write(f"Sesión iniciada como **{st.session_state['jugador_nombre']}**")
    if st.button("Cerrar sesión"):
        limpiar_sesion()
        cookies().remove(COOKIE_SESION)
        # Misma condición de carrera que en login(): sin esta pausa, el
        # rerun corta el ciclo antes de que el navegador borre la cookie.
        time.sleep(0.5)
        st.rerun()

    with st.expander("Cambiar mi PIN"):
        with st.form("form_cambiar_pin"):
            pin_actual = st.text_input("PIN actual", type="password", max_chars=4)
            pin_nuevo = st.text_input("PIN nuevo (4 dígitos)", type="password", max_chars=4)
            pin_nuevo2 = st.text_input("Repite el PIN nuevo", type="password", max_chars=4)
            if st.form_submit_button("Actualizar PIN"):
                if not validar_pin(pin_nuevo):
                    st.error("El PIN nuevo debe ser de 4 dígitos.")
                elif pin_nuevo != pin_nuevo2:
                    st.error("Los PIN nuevos no coinciden.")
                else:
                    fila = cambiar_pin(db(), st.session_state["jugador_id"], pin_actual, pin_nuevo)
                    if fila:
                        crear_sesion_jugador(fila)
                        st.success("PIN actualizado.")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(ERROR_ACCESO)

    if not es_admin:
        with st.expander("Acceso Administrador"):
            admin_password = st.text_input("Contraseña de administrador", type="password",
                                           key="admin_password_input")
            if st.button("Ingresar como admin"):
                expected = get_secret("ADMIN_PASSWORD")
                if (expected and len(expected) >= 16
                        and hmac.compare_digest(admin_password.encode(), expected.encode())):
                    st.session_state["es_admin"] = True
                    st.rerun()
                else:
                    st.error(ERROR_ACCESO)
    else:
        st.success("Sesión de administrador activa")


if __name__ == "__main__":
    main()
