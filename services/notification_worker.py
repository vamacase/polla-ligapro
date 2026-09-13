"""Worker for durable, independently retryable SMTP deliveries."""

from datetime import datetime, timedelta, timezone
from typing import Callable


RETRY_MINUTES = (5, 15, 60, 240)
MAX_ATTEMPTS = 5


def retry_at(now: datetime, attempts: int) -> datetime:
    """Return the next bounded retry time for a failed SMTP attempt."""
    minutes = RETRY_MINUTES[min(max(attempts, 1), len(RETRY_MINUTES)) - 1]
    return now + timedelta(minutes=minutes)


def process_notifications(
    db,
    send: Callable[[str, str, str], bool],
    limit: int = 25,
    now: datetime | None = None,
) -> dict[str, int]:
    """Claim due work, send independently, and persist its next state."""
    now = now or datetime.now(timezone.utc)
    claimed = db.rpc("reclamar_notificaciones", {"p_limit": limit}).execute().data or []
    totals = {"claimed": len(claimed), "sent": 0, "retrying": 0, "failed": 0}

    for notification in claimed:
        payload = notification["payload"]
        try:
            accepted = send(notification["destinatario"], payload["subject"], payload["html"])
        except Exception as error:  # the queue records a safe error instead of stopping peers
            accepted = False
            error_text = str(error)[:500]
        else:
            error_text = "SMTP no aceptó el mensaje" if not accepted else None

        update = {"actualizado_en": now.isoformat()}
        if accepted:
            update.update({"estado": "enviado", "aceptado_smtp_en": now.isoformat(), "ultimo_error": None})
            totals["sent"] += 1
        elif notification["intentos"] >= MAX_ATTEMPTS:
            update.update({"estado": "fallido", "ultimo_error": error_text})
            totals["failed"] += 1
        else:
            update.update(
                {
                    "estado": "pendiente",
                    "proximo_intento": retry_at(now, notification["intentos"]).isoformat(),
                    "ultimo_error": error_text,
                }
            )
            totals["retrying"] += 1
        db.table("notificaciones").update(update).eq("id", notification["id"]).execute()

    return totals
