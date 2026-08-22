"""Envío de correos de la polla vía Gmail SMTP (biblioteca estándar, sin
dependencias nuevas).

Requiere GMAIL_USER y GMAIL_APP_PASSWORD en el entorno (.env/.env.prod o
st.secrets) — GMAIL_APP_PASSWORD es una "contraseña de aplicación" generada
en myaccount.google.com/apppasswords (requiere verificación en 2 pasos
activada), no la contraseña normal de la cuenta.

Si no están configuradas, las funciones de envío no hacen nada (nunca
lanzan excepción) — para no interrumpir el guardado de predicciones ni el
workflow de sync si el correo falla o no está habilitado.

Plantillas: HTML de tablas con estilos inline (no flexbox/grid — soporte
real en Gmail/Outlook/Hotmail), con la misma paleta e identidad visual de
la app (verde salvia + crema, tarjetas blancas con sombra). Diseñadas y
validadas con /design antes de implementarlas aquí.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
APP_URL = "https://polla-papers-ligapro.streamlit.app"

_BG = "#EDEDE6"
_CARD = "#F7F7F2"
_WHITE = "#FFFFFF"
_TEXT = "#2F3E38"
_MUTED = "#7A8A83"
_FAINT = "#9AA6A0"
_ACCENT = "#6B9080"
_ACCENT_SOFT = "#EEF3F0"
_BORDER = "#F0F0EB"
_EXACTO = "#7FB09A"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif"


def _credenciales():
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        try:
            import streamlit as st
            user = user or st.secrets["GMAIL_USER"]
            password = password or st.secrets["GMAIL_APP_PASSWORD"]
        except Exception:
            pass
    return user, password


def _enviar_html(destinatarios: list[str], asunto: str, html: str) -> bool:
    """Un solo mensaje POR destinatario (cada uno ve solo su propia dirección
    en "Para" — nunca la lista completa de correos de los demás jugadores)."""
    user, password = _credenciales()
    destinatarios = [d for d in destinatarios if d]
    if not user or not password or not destinatarios:
        return False

    ok_alguno = False
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(user, password)
            for destinatario in destinatarios:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = asunto
                msg["From"] = f"Polla Liga Pro <{user}>"
                msg["To"] = destinatario
                msg.attach(MIMEText(html, "html"))
                try:
                    server.sendmail(user, [destinatario], msg.as_string())
                    ok_alguno = True
                except Exception:
                    continue
        return ok_alguno
    except Exception:
        return False


def _envolver(icono: str, titulo: str, intro: str, cuerpo: str, boton_texto: str, pie: str) -> str:
    """Layout compartido: icono redondo, tarjeta crema, contenido, botón, pie."""
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:32px 16px; background:{_BG}; font-family:{_FONT};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px; margin:0 auto;">
<tr><td style="padding:0 0 16px; text-align:center;">
  <div style="width:56px;height:56px;border-radius:50%;background:{_WHITE};margin:0 auto 8px;display:inline-flex;align-items:center;justify-content:center;font-size:26px;box-shadow:0 1px 3px rgba(47,62,56,0.10);">{icono}</div>
</td></tr>
<tr><td style="background:{_CARD}; border-radius:16px; padding:28px 24px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td>
      <span style="font-size:20px; font-weight:800; color:{_TEXT};">{titulo}</span>
    </td></tr>
    <tr><td style="padding-top:6px; padding-bottom:20px;">
      <span style="font-size:14px; color:{_MUTED}; line-height:1.5;">{intro}</span>
    </td></tr>
    {cuerpo}
    <tr><td style="padding-top:22px; text-align:center;">
      <a href="{APP_URL}" style="display:inline-block; background:{_ACCENT}; color:#fff; font-weight:700; font-size:14px; text-decoration:none; padding:11px 28px; border-radius:999px;">{boton_texto}</a>
    </td></tr>
  </table>
</td></tr>
<tr><td style="padding:18px 8px 0; text-align:center;">
  <span style="font-size:12px; color:{_FAINT};">Polla Liga Pro Ecuador · {pie}</span>
</td></tr>
</table>
</body>
</html>"""


def _marcador(gl, gv) -> str:
    return (f'<span style="display:inline-block; background:{_ACCENT_SOFT}; color:{_TEXT}; '
            f'font-weight:800; font-size:15px; padding:4px 12px; border-radius:8px; '
            f'font-variant-numeric:tabular-nums;">{gl}&nbsp;–&nbsp;{gv}</span>')


def enviar_confirmacion(destinatario: str, nombre_jugador: str, ronda, filas: list[dict]) -> bool:
    """filas: [{"local": str, "visita": str, "gl": int, "gv": int}, ...]

    Se manda cada vez que el jugador guarda (incluye reguardados/ediciones
    antes del cierre de cada partido — no es un aviso de bloqueo)."""
    filas_html = "".join(
        f"""<tr>
          <td style="padding:14px 16px; font-size:14px; font-weight:600; color:{_TEXT};">{f['local']}</td>
          <td style="padding:14px 10px; text-align:center; width:64px;">{_marcador(f['gl'], f['gv'])}</td>
          <td style="padding:14px 16px; font-size:14px; font-weight:600; color:{_TEXT}; text-align:right;">{f['visita']}</td>
        </tr>
        <tr><td colspan="3" style="border-top:1px solid {_BORDER};"></td></tr>"""
        for f in filas
    )
    cuerpo = f"""
    <tr><td>
      <span style="display:inline-block; background:{_EXACTO}; color:#1F3D30; font-weight:700; font-size:12px; letter-spacing:0.03em; text-transform:uppercase; padding:5px 12px; border-radius:999px;">✅ Guardado</span>
    </td></tr>
    <tr><td style="height:14px;"></td></tr>
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_WHITE}; border-radius:12px; box-shadow:0 1px 3px rgba(47,62,56,0.08); overflow:hidden;">
        {filas_html}
      </table>
    </td></tr>
    """
    html = _envolver(
        "⚽", f"Tus predicciones — Fecha {ronda}",
        f"Hola {nombre_jugador}, guardamos lo siguiente. Puedes seguir editando cada partido hasta que empiece.",
        cuerpo, "Ver en la app",
        "si tú no hiciste este cambio, entra a la app y revisa tu PIN.")
    return _enviar_html([destinatario], f"Polla Liga Pro — predicciones guardadas (Fecha {ronda})", html)


def enviar_todos_predijeron(destinatarios: list[str], ronda, partidos: list[dict]) -> bool:
    """partidos: [{"local": str, "visita": str,
                    "grupos": {"local": [{"nombre","gl","gv"}, ...], "empate": [...], "visita": [...]}}, ...]

    Se manda a todos los jugadores cuando el último termina de predecir la
    fecha completa — la misma revelación de "quién le fue a quién" que hoy
    se ve dentro de la app, agrupada por resultado (local/empate/visita)."""

    def _grupo_html(etiqueta: str, filas: list[dict], destacado: bool) -> str:
        if not filas:
            return ""
        filas_html = "".join(
            f"""<tr>
              <td style="padding:2px 0; font-size:13px; color:{_EXACTO if f.get('es_exacto') else (_TEXT if destacado else '#6B7570')}; font-weight:{'800' if f.get('es_exacto') else ('600' if destacado else '400')};">{'✓ ' if f.get('es_exacto') else ''}{f['nombre']}</td>
              <td style="padding:2px 0; text-align:right; font-size:13px; font-weight:{'800' if f.get('es_exacto') else ('700' if destacado else '600')}; color:{_EXACTO if f.get('es_exacto') else (_TEXT if destacado else '#6B7570')};">{f['gl']}-{f['gv']}</td>
            </tr>"""
            for f in filas
        )
        etiqueta_html = (
            f'<span style="font-size:12px; font-weight:700; color:#3E6A56; text-transform:uppercase; letter-spacing:0.02em;">✓ {etiqueta} ({len(filas)})</span>'
            if destacado else
            f'<span style="font-size:12px; font-weight:700; color:{_FAINT}; text-transform:uppercase; letter-spacing:0.02em;">{etiqueta} ({len(filas)})</span>'
        )
        contenedor_estilo = (
            f"border-left:3px solid {_ACCENT}; background:{_ACCENT_SOFT}; border-radius:0 8px 8px 0; padding:8px 12px;"
            if destacado else "padding:6px 0;"
        )
        return f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="{contenedor_estilo} margin-bottom:4px;">
          <tr><td>
            {etiqueta_html}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:4px;">
              {filas_html}
            </table>
          </td></tr>
        </table>"""

    bloques = []
    for p in partidos:
        grupos = p["grupos"]
        bloques.append(f"""
        <tr><td style="background:{_WHITE}; border-radius:12px; box-shadow:0 1px 3px rgba(47,62,56,0.08); overflow:hidden;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:14px 16px 10px;">
              <span style="font-size:14.5px; font-weight:700; color:{_TEXT};">{p['local']} vs {p['visita']}</span>
            </td></tr>
            <tr><td style="padding:0 16px 16px;">
              {_grupo_html(p['local'], grupos['local'], True)}
              {_grupo_html("Empate", grupos['empate'], False)}
              {_grupo_html(p['visita'], grupos['visita'], False)}
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="height:14px;"></td></tr>""")

    cuerpo = "".join(bloques)
    html = _envolver(
        "🔓", f"Ya predijeron los 10 — Fecha {ronda}",
        "Así va a jugar cada quien esta fecha:",
        cuerpo, "Ver todos los partidos",
        "entra a la app para ver el detalle de marcadores exactos.")
    return _enviar_html(destinatarios, f"Polla Liga Pro — predicciones de todos (Fecha {ronda})", html)


def enviar_fecha_terminada(destinatarios: list[str], ronda, resultados: list[dict], ranking: list[dict]) -> bool:
    """resultados: [{"local": str, "visita": str, "gl": int, "gv": int}, ...]
    ranking: [{"nombre": str, "puntos": int}, ...] ya ordenado por puntos desc.
    """
    res_html = "".join(
        f"""<tr>
          <td style="padding:13px 16px 2px; font-size:11px; color:{_FAINT};" colspan="3">{r.get('fecha', '')}</td>
        </tr>
        <tr>
          <td style="padding:0 16px 13px; font-size:13.5px; font-weight:600; color:{_TEXT};">{r['local']}</td>
          <td style="padding:0 8px 13px; text-align:center; width:60px;">{_marcador(r['gl'], r['gv'])}</td>
          <td style="padding:0 16px 13px; font-size:13.5px; font-weight:600; color:{_TEXT}; text-align:right;">{r['visita']}</td>
        </tr>
        <tr><td colspan="3" style="border-top:1px solid {_BORDER};"></td></tr>"""
        for r in resultados
    )
    medallas = {0: "🥇", 1: "🥈", 2: "🥉"}
    rank_filas = []
    for i, r in enumerate(ranking):
        destacado = i == 0
        detalle = f"{r.get('exactos', 0)} exactos · {r.get('jugados', 0)} jugados"
        rank_filas.append(f"""<tr style="{'background:' + _ACCENT_SOFT + ';' if destacado else ''}">
          <td style="padding:12px 8px 12px 16px; font-size:{'14px' if destacado else '13px'}; color:{_TEXT if destacado else _FAINT}; white-space:nowrap;">{medallas.get(i, f'#{i + 1}')}</td>
          <td style="padding:12px 4px;">
            <div style="font-size:14px; font-weight:{'800' if destacado else '600'}; color:{_TEXT};">{r['nombre']}</div>
            <div style="font-size:11.5px; color:{_FAINT};">{detalle}</div>
          </td>
          <td style="padding:12px 16px; text-align:right; font-size:{'15px' if destacado else '14px'}; font-weight:800; color:{_ACCENT if destacado else _TEXT}; white-space:nowrap;">{r['puntos']} pts</td>
        </tr>
        <tr><td colspan="3" style="border-top:1px solid {_BORDER};"></td></tr>""")
    rank_html = "".join(rank_filas)

    cuerpo = f"""
    <tr><td style="padding-bottom:8px;">
      <span style="font-size:12px; font-weight:700; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.03em;">Resultados</span>
    </td></tr>
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_WHITE}; border-radius:12px; box-shadow:0 1px 3px rgba(47,62,56,0.08); overflow:hidden; margin-bottom:24px;">
        {res_html}
      </table>
    </td></tr>
    <tr><td style="padding-bottom:8px;">
      <span style="font-size:12px; font-weight:700; color:{_MUTED}; text-transform:uppercase; letter-spacing:0.03em;">Tabla de posiciones</span>
    </td></tr>
    <tr><td>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_WHITE}; border-radius:12px; box-shadow:0 1px 3px rgba(47,62,56,0.08); overflow:hidden;">
        {rank_html}
      </table>
    </td></tr>
    """
    html = _envolver(
        "🏁", f"Fecha {ronda} terminada",
        "Estos fueron los resultados y así quedó la tabla:",
        cuerpo, "Ver tabla completa",
        "entra a la app para ver el detalle completo.")
    return _enviar_html(destinatarios, f"Polla Liga Pro — resultados y tabla (Fecha {ronda})", html)
