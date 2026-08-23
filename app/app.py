"""Polla Liga Pro Ecuador — webapp Streamlit (predicciones + ranking entre amigos)."""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from db import get_client  # noqa: E402
from email_notif import enviar_confirmacion, enviar_todos_predijeron  # noqa: E402
from streamlit_cookies_controller import CookieController  # noqa: E402

st.set_page_config(page_title="Polla Liga Pro", page_icon="⚽", layout="centered")

DIAS_SESION = 30


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
st.html("""
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

/* Fila compacta de pronóstico ("Opción A"): una línea corta por equipo
   (escudo+nombre+su marcador) en vez de equipo arriba/input abajo por
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
    .block-container { padding-left: 0.8rem; padding-right: 0.8rem; }
    div[data-testid="stNumberInput"] input { font-size: 1rem; padding: 0.5rem; }
    h3 { font-size: 1.1rem; }
    .polla-equipo { min-height: 4rem; }
    /* Botones +/- del marcador: área táctil grande en móvil (112px).
       Testids verificados en Streamlit 1.60.0. */
    [data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {
        min-width: 7rem !important;
        min-height: 7rem !important;
    }
    [data-testid="stNumberInputStepUp"] svg, [data-testid="stNumberInputStepDown"] svg {
        width: 2.8rem !important;
        height: 2.8rem !important;
    }
}
</style>
""")


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
    """Marcador exacto y acierto de solo 1X2 valen lo mismo (1pt), pero se
    distinguen visualmente — es_exacto viene de la vista v_puntos."""
    if puntos is None:
        return '<span class="polla-pill polla-pill--na">Pendiente</span>'
    if puntos == 1 and es_exacto:
        return '<span class="polla-pill polla-pill--exacto">Exacto</span>'
    if puntos == 1:
        return '<span class="polla-pill polla-pill--1x2">1X2</span>'
    if puntos == 0:
        return '<span class="polla-pill polla-pill--fallo">Fallo</span>'
    return '<span class="polla-pill polla-pill--na">—</span>'


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
    """Para una fecha, cuenta cuántos partidos predijo cada jugador.

    Nunca expone los marcadores que cada quien predijo — solo si ya
    completó su predicción o no — para no arruinar la sorpresa antes de
    que cierren los partidos (ver reglamento: la apuesta debe publicarse
    sin haber visto la de los demás).
    """
    partidos_ronda = db().table("partidos").select("id").eq("fecha_ronda", ronda).execute().data
    ids_ronda = [p["id"] for p in partidos_ronda]
    total = len(ids_ronda)
    jugadores = db().table("jugadores").select("id, nombre").order("nombre").execute().data
    preds = (db().table("predicciones").select("jugador_id, partido_id")
             .in_("partido_id", ids_ronda).execute().data if ids_ronda else [])
    contadas = {}
    for pr in preds:
        contadas[pr["jugador_id"]] = contadas.get(pr["jugador_id"], 0) + 1
    return [{"id": j["id"], "nombre": j["nombre"], "n": contadas.get(j["id"], 0), "total": total}
            for j in jugadores]


def fecha_totalmente_predicha(estado_jugadores) -> bool:
    """True si TODOS los jugadores ya predijeron TODOS los partidos de la fecha."""
    return bool(estado_jugadores) and all(e["total"] > 0 and e["n"] >= e["total"] for e in estado_jugadores)


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
                       .eq("fecha_ronda", ronda).order("kickoff").execute().data)
    ids_ronda = [p["id"] for p in partidos_ronda]
    todas = (db().table("v_puntos")
             .select("partido_id, gl_pred, gv_pred, es_exacto, jugadores(nombre)")
             .in_("partido_id", ids_ronda).execute().data)
    por_partido = {}
    for f in todas:
        por_partido.setdefault(f["partido_id"], []).append(f)

    cuerpo = []
    for p in partidos_ronda:
        grupos = {"local": [], "empate": [], "visita": []}
        for f in por_partido.get(p["id"], []):
            grupos[clasificar_resultado(f["gl_pred"], f["gv_pred"])].append({
                "nombre": f["jugadores"]["nombre"], "gl": f["gl_pred"], "gv": f["gv_pred"],
                "es_exacto": bool(f["es_exacto"]),
            })
        for g in grupos.values():
            g.sort(key=lambda x: x["nombre"])
        cuerpo.append({"local": p["local"], "visita": p["visita"], "grupos": grupos})

    destinatarios = [j["email"] for j in db().table("jugadores").select("email").execute().data if j["email"]]
    if destinatarios:
        enviar_todos_predijeron(destinatarios, ronda, cuerpo)


def get_admin_pin():
    pin = os.environ.get("ADMIN_PIN")
    if not pin:
        try:
            pin = st.secrets["ADMIN_PIN"]
        except Exception:
            pin = None
    return pin


def login():
    with st.container(border=True, key="card_login"):
        st.markdown(
            f'<div style="text-align:center">{logo(LIGA_ID, 100)}</div>',
            unsafe_allow_html=True)
        st.title("Polla Liga Pro Ecuador")
        jugadores = db().table("jugadores").select("id, nombre").order("nombre").execute().data
        if not jugadores:
            st.error("Aún no hay jugadores registrados. Pídele al admin que te agregue.")
            st.stop()
        nombres = [j["nombre"] for j in jugadores]
        nombre = st.selectbox("¿Quién eres?", nombres)
        pin = st.text_input("PIN", type="password", max_chars=4)
        if st.button("Entrar", type="primary"):
            fila = db().table("jugadores").select("id, pin").eq("nombre", nombre).single().execute().data
            if fila and str(fila["pin"]) == pin:
                st.session_state["jugador_id"] = fila["id"]
                st.session_state["jugador_nombre"] = nombre
                cookies().set("polla_jugador_id", str(fila["id"]),
                               max_age=DIAS_SESION * 24 * 3600)
                st.rerun()
            else:
                st.error("PIN incorrecto.")

    st.markdown(
        f'<div style="text-align:center; color:var(--polla-muted); font-size:0.75em; margin-top:1rem">'
        f'© {datetime.now().year} Vicente Macas Espinosa</div>',
        unsafe_allow_html=True)


def cargar_partidos_abiertos():
    ahora = datetime.now(timezone.utc).isoformat()
    return (db().table("partidos").select("*")
            .eq("cerrado", False).gt("kickoff", ahora)
            .order("kickoff").execute().data)


def cargar_predicciones(jugador_id):
    filas = db().table("predicciones").select("*").eq("jugador_id", jugador_id).execute().data
    return {f["partido_id"]: f for f in filas}


def tarjeta_partido(p, mis_pred):
    """Fila compacta: hora+badge, luego una línea corta por equipo (escudo +
    nombre + su marcador). Streamlit apila st.columns en una sola columna
    vertical bajo cierto ancho SIN importar cuántas haya (incluso 2,
    comprobado) — forzar layout horizontal vía CSS no es fiable porque
    Streamlit recalcula el flex-flow de sus bloques por JS en cada resize.
    Por eso cada equipo va en su propia línea (más compacta que la tarjeta
    anterior: equipo+goles comparten línea en vez de equipo arriba/input
    abajo por separado)."""
    existente = mis_pred.get(p["id"])
    with st.container(border=True, key=f"card_partido_{p['id']}"):
        kickoff_local = a_local(p["kickoff"]).strftime("%a %d/%m %H:%M")
        c_info, c_badge = st.columns([2, 1])
        with c_info:
            st.markdown(f'<div class="polla-fila-hora">{kickoff_local}</div>', unsafe_allow_html=True)
        with c_badge:
            st.markdown(badge_cuenta_regresiva(p["kickoff"]), unsafe_allow_html=True)

        st.markdown(
            f'<div class="polla-fila-equipo">{logo(p.get("local_id"), 22)}<span>{p["local"]}</span></div>',
            unsafe_allow_html=True)
        gl = st.number_input("Goles", min_value=0, max_value=15, step=1,
                              value=existente["gl_pred"] if existente else 0,
                              key=f"gl_{p['id']}", label_visibility="collapsed")

        st.markdown(
            f'<div class="polla-fila-equipo">{logo(p.get("visita_id"), 22)}<span>{p["visita"]}</span></div>',
            unsafe_allow_html=True)
        gv = st.number_input("Goles", min_value=0, max_value=15, step=1,
                              value=existente["gv_pred"] if existente else 0,
                              key=f"gv_{p['id']}", label_visibility="collapsed")
    return gl, gv


def vista_predicciones():
    jugador_id = st.session_state["jugador_id"]
    st.markdown(
        f'<div style="text-align:center">{logo(LIGA_ID, 70)}</div>',
        unsafe_allow_html=True)
    st.subheader(f"Hola, {st.session_state['jugador_nombre']} 👋")

    # Mensaje persistente: el st.success de más abajo se mostraba un instante
    # antes del st.rerun() y desaparecía sin que el usuario lo notara, dejando
    # la sensación de que "no pasó nada" al guardar. Se guarda en
    # session_state para que sobreviva al rerun y se vea arriba de la página.
    if "mensaje_guardado" in st.session_state:
        guardados, rechazados = st.session_state.pop("mensaje_guardado")
        if guardados:
            st.success(f"✅ ¡{guardados} predicciones guardadas correctamente!")
        if rechazados:
            st.error("⚠️ No se guardaron (el partido ya inició): " + ", ".join(rechazados))

    partidos = cargar_partidos_abiertos()
    if not partidos:
        st.info("No hay partidos abiertos para predecir por ahora. Vuelve pronto.")
        return

    mis_pred = cargar_predicciones(jugador_id)
    st.caption("Predice el marcador. 1 pt si aciertas el resultado (exacto o solo 1X2), 0 si fallas.")

    rondas = sorted({p["fecha_ronda"] for p in partidos}, key=lambda r: (r is None, r))
    ronda_sel = selector_fecha(rondas, key="ronda_pred")
    partidos_ronda = [p for p in partidos if p["fecha_ronda"] == ronda_sel]

    faltantes = [p for p in partidos_ronda if p["id"] not in mis_pred]
    if faltantes:
        st.warning(f"⚠️ Te faltan {len(faltantes)} de {len(partidos_ronda)} partidos por predecir en esta fecha.")
    else:
        st.success(f"✅ Ya predijiste los {len(partidos_ronda)} partidos de esta fecha.")

    # Seguro: una vez que TODOS predijeron TODA la fecha, se revela en "Mis
    # predicciones" — a partir de ahí ya no se puede editar, para que nadie
    # vea las apuestas de los demás y luego cambie la suya antes del cierre.
    if fecha_totalmente_predicha(calcular_estado_prediccion(ronda_sel)):
        st.info("🔒 Todos ya predijeron esta fecha — las predicciones quedaron congeladas. "
                "Ve a 'Mis predicciones' para verlas todas.")
        return

    with st.form("form_predicciones"):
        valores = {}
        for i, p in enumerate(partidos_ronda, start=1):
            st.caption(f"Partido {i}")
            gl, gv = tarjeta_partido(p, mis_pred)
            valores[p["id"]] = (gl, gv)

        enviado = st.form_submit_button("Guardar predicciones", type="primary")
        if enviado:
            # Revalidar contra la hora real al momento del envío: el formulario
            # pudo abrirse minutos antes con partidos aún abiertos, pero el
            # jugador puede tardarse en enviar y que alguno ya haya arrancado.
            ids = list(valores.keys())
            frescos = {p["id"]: p for p in db().table("partidos").select("id, local, visita, kickoff, cerrado")
                       .in_("id", ids).execute().data}
            ahora = datetime.now(timezone.utc)
            guardados, rechazados = 0, []
            confirmadas = []
            for partido_id, (gl, gv) in valores.items():
                p = frescos.get(partido_id)
                if not p or p["cerrado"] or pd.to_datetime(p["kickoff"]) <= ahora:
                    rechazados.append(p["local"] + " vs " + p["visita"] if p else f"partido {partido_id}")
                    continue
                db().table("predicciones").upsert({
                    "jugador_id": jugador_id, "partido_id": partido_id,
                    "gl_pred": int(gl), "gv_pred": int(gv),
                    "actualizado_en": ahora.isoformat(),
                }, on_conflict="jugador_id,partido_id").execute()
                guardados += 1
                confirmadas.append({"local": p["local"], "visita": p["visita"], "gl": int(gl), "gv": int(gv)})

            if confirmadas:
                jugador = db().table("jugadores").select("email").eq("id", jugador_id).single().execute().data
                if jugador and jugador.get("email"):
                    enviar_confirmacion(
                        jugador["email"], st.session_state["jugador_nombre"], ronda_sel, confirmadas)
                if fecha_totalmente_predicha(calcular_estado_prediccion(ronda_sel)):
                    intentar_notificar_todos_predijeron(ronda_sel)

            st.session_state["mensaje_guardado"] = (guardados, rechazados)
            st.rerun()


def fila_estado_jugador(nombre, completo, es_yo):
    icono = "✅" if completo else "⏳"
    clase = "polla-rank-row polla-rank-row--yo" if es_yo else "polla-rank-row"
    st.markdown(
        f'<div class="{clase}">'
        f'<span style="flex:1; font-weight:{"700" if es_yo else "500"}">{nombre}</span>'
        f'<span style="font-size:1.1em">{icono}</span>'
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

    jugadores = db().table("jugadores").select("id, nombre").execute().data
    partidos = db().table("partidos").select("id, fecha_ronda").execute().data
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
    puntos_filas = []
    if ids_partidos:
        puntos_filas = (db().table("v_puntos").select("jugador_id, puntos, es_exacto")
                         .in_("partido_id", ids_partidos).not_.is_("puntos", "null")
                         .execute().data)

    agregados = {}
    for f in puntos_filas:
        jid = f["jugador_id"]
        acc = agregados.setdefault(
            jid, {"puntos_totales": 0, "aciertos_exactos": 0, "aciertos_1x2": 0, "partidos_predichos": 0})
        acc["puntos_totales"] += f["puntos"]
        acc["aciertos_exactos"] += 1 if f["es_exacto"] else 0
        acc["aciertos_1x2"] += 1 if f["puntos"] == 1 and not f["es_exacto"] else 0
        acc["partidos_predichos"] += 1

    ranking = []
    for j in jugadores:
        acc = agregados.get(
            j["id"], {"puntos_totales": 0, "aciertos_exactos": 0, "aciertos_1x2": 0, "partidos_predichos": 0})
        ranking.append({"jugador_id": j["id"], "nombre": j["nombre"], **acc})
    ranking.sort(key=lambda r: (-r["puntos_totales"], -r["aciertos_exactos"]))

    mi_id = st.session_state.get("jugador_id")
    medallas = {1: "🥇", 2: "🥈", 3: "🥉"}
    COL_EXACTO = "Ptos Resultado\nExacto"
    COL_1X2 = "Ptos Resultado\nGana/Empata/Pierde"
    filas_tabla = []
    for i, fila in enumerate(ranking, start=1):
        nombre = fila["nombre"] + (" 👤" if fila["jugador_id"] == mi_id else "")
        filas_tabla.append({
            "Puesto": medallas.get(i, f"#{i}"),
            "Jugador": nombre,
            "Puntos Totales": fila["puntos_totales"],
            COL_EXACTO: fila["aciertos_exactos"],
            COL_1X2: fila["aciertos_1x2"],
        })
    dfr = pd.DataFrame(filas_tabla)
    st.dataframe(
        dfr, width="stretch", hide_index=True,
        column_config={
            "Puesto": st.column_config.TextColumn(width="small"),
            "Puntos Totales": st.column_config.NumberColumn(width="small"),
            COL_EXACTO: st.column_config.NumberColumn(width="small"),
            COL_1X2: st.column_config.NumberColumn(width="small"),
        })


def vista_resultados():
    st.subheader("📋 Últimos resultados")
    cerrados = (db().table("partidos").select("*").eq("cerrado", True)
                .not_.is_("gl_real", "null").order("kickoff", desc=True).limit(20).execute().data)
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
            c1, c2, c3 = st.columns([3, 1, 3])
            with c1:
                st.markdown(
                    f'<div style="text-align:right; font-size:0.85em">{p["local"]} {logo(p.get("local_id"), 28)}</div>',
                    unsafe_allow_html=True)
            with c2:
                st.markdown(
                    f'<div style="text-align:center"><span class="polla-pill" style="background:var(--polla-card); '
                    f'border:1px solid var(--polla-border); font-size:1.1rem">{p["gl_real"]} - {p["gv_real"]}</span></div>',
                    unsafe_allow_html=True)
            with c3:
                st.markdown(
                    f'<div style="font-size:0.85em">{logo(p.get("visita_id"), 28)} {p["visita"]}</div>',
                    unsafe_allow_html=True)


def vista_mis_predicciones():
    jugador_id = st.session_state["jugador_id"]
    st.subheader("📝 Mis predicciones")

    # El selector de fecha se basa en TODOS los partidos cargados, no solo
    # en los que el jugador actual ya predijo — si no, alguien que aún no
    # predice nada en una fecha ni siquiera podría seleccionarla para ver
    # el checklist de quién sí lo hizo.
    partidos_todos = db().table("partidos").select("fecha_ronda, cerrado").execute().data
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
        fila_estado_jugador(e["nombre"], completo, e["id"] == jugador_id)

    # Revelación: recién cuando LOS 10 terminaron de predecir TODA la fecha
    # se muestra qué puso cada quien en cada partido. Antes de eso nadie ve
    # nada — ver esto y luego editar la propia predicción sería copiarse.
    if fecha_totalmente_predicha(estado_jugadores):
        st.markdown("#### 🔓 Predicciones de todos — fecha completa")
        partidos_ronda_full = (db().table("partidos")
                                .select("id, local, visita, kickoff, gl_real, gv_real")
                                .eq("fecha_ronda", ronda_sel).order("kickoff").execute().data)
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
    filas = (db().table("v_puntos").select("*, partidos(local, visita, kickoff, fecha_ronda)")
             .eq("jugador_id", jugador_id).execute().data)
    de_la_ronda = sorted(
        (f for f in filas if f["partidos"]["fecha_ronda"] == ronda_sel),
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

    jugadores = db().table("jugadores").select("id, nombre, pin, email").order("nombre").execute().data
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
            f"{a_local(p['kickoff']).strftime('%a %d/%m %H:%M')} {badge_cuenta_regresiva(p['kickoff'])}",
            unsafe_allow_html=True)

    rondas = sorted({p["fecha_ronda"] for p in partidos if p["fecha_ronda"] is not None}, reverse=True)
    ronda_sel = selector_fecha(rondas, key="ronda_admin")
    partidos_ronda = sorted(
        (p for p in partidos if p["fecha_ronda"] == ronda_sel), key=lambda p: p["kickoff"])

    st.markdown("#### Partidos de la fecha")
    tabla_partidos = pd.DataFrame([{
        "Partido": f"{p['local']} vs {p['visita']}",
        "Hora (Ecuador)": a_local(p["kickoff"]).strftime("%a %d/%m %H:%M"),
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
    st.dataframe(pd.DataFrame([{"Jugador": j["nombre"], "PIN": j["pin"]} for j in jugadores]),
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
    """Si el navegador trae la cookie de sesión (dura DIAS_SESION), reingresa
    al jugador sin pedirle PIN otra vez — evita re-login en cada visita."""
    try:
        jugador_id = cookies().get("polla_jugador_id")
    except TypeError:
        # El componente de cookies aún no resolvió su valor real en este
        # rerun (queda None en vez de {} de forma transitoria) — se
        # intenta de nuevo en el siguiente rerun natural de Streamlit.
        return
    if not jugador_id:
        return
    fila = db().table("jugadores").select("id, nombre").eq("id", jugador_id).execute().data
    if fila:
        st.session_state["jugador_id"] = fila[0]["id"]
        st.session_state["jugador_nombre"] = fila[0]["nombre"]


def main():
    if "jugador_id" not in st.session_state:
        restaurar_sesion_desde_cookie()
    if "jugador_id" not in st.session_state:
        login()
        return

    es_admin = st.session_state.get("es_admin", False)
    nombres_tabs = ["Predecir", "Ranking", "Resultados", "Mis predicciones"]
    if es_admin:
        nombres_tabs.append("Admin")
    tabs = st.tabs(nombres_tabs)
    with tabs[0]:
        vista_predicciones()
    with tabs[1]:
        vista_ranking()
    with tabs[2]:
        vista_resultados()
    with tabs[3]:
        vista_mis_predicciones()
    if es_admin:
        with tabs[4]:
            vista_admin()

    with st.sidebar:
        st.write(f"Sesión: **{st.session_state['jugador_nombre']}**")
        if st.button("Cerrar sesión"):
            del st.session_state["jugador_id"]
            del st.session_state["jugador_nombre"]
            st.session_state.pop("es_admin", None)
            cookies().remove("polla_jugador_id")
            st.rerun()

        if not es_admin:
            with st.expander("Acceso Administrador"):
                admin_pin = st.text_input("PIN de administrador", type="password",
                                           max_chars=4, key="admin_pin_input")
                if st.button("Ingresar como admin"):
                    if get_admin_pin() and admin_pin == get_admin_pin():
                        st.session_state["es_admin"] = True
                        st.rerun()
                    else:
                        st.error("PIN de administrador incorrecto.")
        else:
            st.success("Sesión de administrador activa")

        with st.expander("Cambiar mi PIN"):
            with st.form("form_cambiar_pin"):
                pin_actual = st.text_input("PIN actual", type="password", max_chars=4)
                pin_nuevo = st.text_input("PIN nuevo (4 dígitos)", type="password", max_chars=4)
                pin_nuevo2 = st.text_input("Repite el PIN nuevo", type="password", max_chars=4)
                if st.form_submit_button("Actualizar PIN"):
                    fila = (db().table("jugadores").select("pin")
                            .eq("id", st.session_state["jugador_id"]).single().execute().data)
                    if not fila or str(fila["pin"]) != pin_actual:
                        st.error("El PIN actual no es correcto.")
                    elif not (pin_nuevo.isdigit() and len(pin_nuevo) == 4):
                        st.error("El PIN nuevo debe ser de 4 dígitos.")
                    elif pin_nuevo != pin_nuevo2:
                        st.error("Los PIN nuevos no coinciden.")
                    else:
                        db().table("jugadores").update({"pin": pin_nuevo}).eq(
                            "id", st.session_state["jugador_id"]).execute()
                        st.success("PIN actualizado.")


if __name__ == "__main__":
    main()
