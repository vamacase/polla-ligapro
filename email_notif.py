"""Envío de correo de confirmación de predicciones vía Gmail SMTP (biblioteca
estándar, sin dependencias nuevas).

Requiere GMAIL_USER y GMAIL_APP_PASSWORD en el entorno (.env/.env.prod o
st.secrets) — GMAIL_APP_PASSWORD es una "contraseña de aplicación" generada
en myaccount.google.com/apppasswords (requiere verificación en 2 pasos
activada), no la contraseña normal de la cuenta.

Si no están configuradas, enviar_confirmacion() no hace nada (no rompe el
guardado de predicciones si el correo falla o no está habilitado).
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


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


def enviar_confirmacion(destinatario: str, nombre_jugador: str, ronda, filas: list[dict]) -> bool:
    """filas: [{"local": str, "visita": str, "gl": int, "gv": int}, ...]

    Devuelve True si se envió, False si no hay credenciales configuradas o
    el envío falló — nunca lanza excepción, para no interrumpir el flujo
    de guardado de predicciones.
    """
    user, password = _credenciales()
    if not user or not password or not destinatario:
        return False

    filas_html = "".join(
        f"<tr><td style='padding:6px 10px'>{f['local']}</td>"
        f"<td style='padding:6px 10px; text-align:center; font-weight:700'>{f['gl']} - {f['gv']}</td>"
        f"<td style='padding:6px 10px'>{f['visita']}</td></tr>"
        for f in filas
    )
    html = f"""
    <div style="font-family:sans-serif; color:#2F3E38">
      <h2 style="color:#6B9080">✅ Predicciones guardadas — Fecha {ronda}</h2>
      <p>Hola {nombre_jugador}, confirmamos que guardamos tus predicciones:</p>
      <table style="border-collapse:collapse; width:100%; max-width:480px">
        {filas_html}
      </table>
      <p style="color:#7A8A83; font-size:0.85em; margin-top:20px">
        Polla Liga Pro Ecuador — si tú no hiciste este cambio, entra a la app y revisa tu PIN.
      </p>
    </div>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Polla Liga Pro — predicciones guardadas (Fecha {ronda})"
    msg["From"] = f"Polla Liga Pro <{user}>"
    msg["To"] = destinatario
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.login(user, password)
            server.sendmail(user, [destinatario], msg.as_string())
        return True
    except Exception:
        return False
