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

st.set_page_config(page_title="Polla Liga Pro", page_icon="⚽", layout="centered")

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
.polla-pill--3 { background:var(--polla-exacto); }
.polla-pill--1 { background:var(--polla-1x2); }
.polla-pill--0 { background:var(--polla-fallo); }
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

@media (max-width: 640px) {
    .block-container { padding-left: 0.8rem; padding-right: 0.8rem; }
    div[data-testid="stNumberInput"] input { font-size: 1rem; padding: 0.5rem; }
    h3 { font-size: 1.1rem; }
    .polla-equipo { min-height: 4rem; }
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


def pill_puntos(puntos) -> str:
    if puntos is None:
        return '<span class="polla-pill polla-pill--na">Pendiente</span>'
    etiquetas = {3: "Exacto", 1: "1X2", 0: "Fallo"}
    clase = f"polla-pill--{puntos}" if puntos in etiquetas else "polla-pill--na"
    texto = etiquetas.get(puntos, "—")
    return f'<span class="polla-pill {clase}">{texto}</span>'


def selector_fecha(rondas, key, label="Selecciona la fecha"):
    opciones = [f"Fecha {r}" if r is not None else "Fecha sin definir" for r in rondas]
    idx = st.selectbox(label, range(len(rondas)), format_func=lambda i: opciones[i], key=key)
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
    existente = mis_pred.get(p["id"])
    with st.container(border=True, key=f"card_partido_{p['id']}"):
        kickoff_local = a_local(p["kickoff"]).strftime("%a %d/%m %H:%M")
        c_info, c_badge = st.columns([2, 1])
        with c_info:
            st.caption(kickoff_local)
        with c_badge:
            st.markdown(badge_cuenta_regresiva(p["kickoff"]), unsafe_allow_html=True)

        c1, c2, c3 = st.columns([2, 1, 2])
        with c1:
            st.markdown(
                f'<div class="polla-equipo">{logo(p.get("local_id"), 40)}<br>'
                f'<span>{p["local"]}</span></div>',
                unsafe_allow_html=True)
            gl = st.number_input("Goles", min_value=0, max_value=15, step=1,
                                  value=existente["gl_pred"] if existente else 0,
                                  key=f"gl_{p['id']}", label_visibility="collapsed")
        with c2:
            st.markdown('<div class="polla-vs">—</div>', unsafe_allow_html=True)
        with c3:
            st.markdown(
                f'<div class="polla-equipo">{logo(p.get("visita_id"), 40)}<br>'
                f'<span>{p["visita"]}</span></div>',
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
    st.caption("Predice el marcador exacto. 3 pts si aciertas el marcador, 1 pt si aciertas el resultado (1X2), 0 si fallas.")

    rondas = sorted({p["fecha_ronda"] for p in partidos}, key=lambda r: (r is None, r))
    ronda_sel = selector_fecha(rondas, key="ronda_pred")
    partidos_ronda = [p for p in partidos if p["fecha_ronda"] == ronda_sel]

    faltantes = [p for p in partidos_ronda if p["id"] not in mis_pred]
    if faltantes:
        st.warning(f"⚠️ Te faltan {len(faltantes)} de {len(partidos_ronda)} partidos por predecir en esta fecha.")
    else:
        st.success(f"✅ Ya predijiste los {len(partidos_ronda)} partidos de esta fecha.")

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
            st.session_state["mensaje_guardado"] = (guardados, rechazados)
            st.rerun()


def fila_ranking(i, fila, es_yo):
    medallas = {1: "🥇", 2: "🥈", 3: "🥉"}
    medalla = medallas.get(i, f"#{i}")
    clase = "polla-rank-row polla-rank-row--yo" if es_yo else "polla-rank-row"
    st.markdown(
        f'<div class="{clase}">'
        f'<span class="polla-medalla">{medalla}</span>'
        f'<span style="flex:1; font-weight:{"700" if es_yo else "500"}">{fila["nombre"]}</span>'
        f'<span style="font-size:0.85em; color:var(--polla-muted)">{fila["aciertos_exactos"]} exactos · {fila["partidos_predichos"]} jugados</span>'
        f'<span style="font-weight:700; font-size:1.1em; margin-left:0.6rem">{fila["puntos_totales"]} pts</span>'
        f'</div>',
        unsafe_allow_html=True)


def fila_estado_jugador(nombre, completo, es_yo):
    icono = "✅" if completo else "⏳"
    clase = "polla-rank-row polla-rank-row--yo" if es_yo else "polla-rank-row"
    st.markdown(
        f'<div class="{clase}">'
        f'<span style="flex:1; font-weight:{"700" if es_yo else "500"}">{nombre}</span>'
        f'<span style="font-size:1.1em">{icono}</span>'
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
        puntos_filas = (db().table("v_puntos").select("jugador_id, puntos")
                         .in_("partido_id", ids_partidos).not_.is_("puntos", "null")
                         .execute().data)

    agregados = {}
    for f in puntos_filas:
        jid = f["jugador_id"]
        acc = agregados.setdefault(jid, {"puntos_totales": 0, "aciertos_exactos": 0, "partidos_predichos": 0})
        acc["puntos_totales"] += f["puntos"]
        acc["aciertos_exactos"] += 1 if f["puntos"] == 3 else 0
        acc["partidos_predichos"] += 1

    ranking = []
    for j in jugadores:
        acc = agregados.get(j["id"], {"puntos_totales": 0, "aciertos_exactos": 0, "partidos_predichos": 0})
        ranking.append({"jugador_id": j["id"], "nombre": j["nombre"], **acc})
    ranking.sort(key=lambda r: (-r["puntos_totales"], -r["aciertos_exactos"]))

    mi_id = st.session_state.get("jugador_id")
    for i, fila in enumerate(ranking, start=1):
        fila_ranking(i, fila, fila["jugador_id"] == mi_id)

    with st.expander("Ver tabla completa"):
        dfr = pd.DataFrame(ranking).rename(columns={
            "nombre": "Jugador", "puntos_totales": "Puntos",
            "partidos_predichos": "Partidos predichos", "aciertos_exactos": "Marcadores exactos",
        })[["Jugador", "Puntos", "Marcadores exactos", "Partidos predichos"]]
        dfr.index = range(1, len(dfr) + 1)
        st.dataframe(dfr, width="stretch")


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
    partidos_todos = db().table("partidos").select("fecha_ronda").execute().data
    rondas = sorted({p["fecha_ronda"] for p in partidos_todos if p["fecha_ronda"] is not None}, reverse=True)
    if not rondas:
        st.info("Todavía no hay partidos cargados.")
        return
    ronda_sel = selector_fecha(rondas, key="ronda_mis_pred")

    # Checklist de quién ya predijo esta fecha: solo el estado (✅/⏳), nunca
    # el marcador que cada quien puso — eso arruinaría la apuesta antes de
    # que cierren los partidos.
    st.markdown("#### Quién ya predijo esta fecha")
    estado_jugadores = calcular_estado_prediccion(ronda_sel)
    for e in estado_jugadores:
        completo = e["total"] > 0 and e["n"] >= e["total"]
        fila_estado_jugador(e["nombre"], completo, e["id"] == jugador_id)

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
                st.markdown(pill_puntos(f["puntos"]), unsafe_allow_html=True)


def vista_admin():
    st.subheader("🛠️ Panel de Administrador")

    jugadores = db().table("jugadores").select("id, nombre, pin").order("nombre").execute().data
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


def main():
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
