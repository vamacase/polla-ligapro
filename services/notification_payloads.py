"""Payload construction for notification jobs; this module never sends SMTP."""

from hashlib import sha256
import json

from email_notif import (
    render_confirmacion, render_fecha_terminada, render_ganadores_polla, render_recordatorio_60min,
    render_recordatorio_faltantes, render_todos_predijeron,
)
from repositories.notifications import enqueue_notification


def enqueue_confirmation(
    db,
    recipient: str,
    player_name: str,
    round_number: int,
    rows: list[dict],
    *,
    player_id=None,
    enqueue=enqueue_notification,
) -> bool:
    """Persist a confirmation delivery instead of calling SMTP on the UI path."""
    canonical_rows = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    fingerprint = sha256(canonical_rows.encode("utf-8")).hexdigest()[:16]
    subject, html = render_confirmacion(player_name, round_number, rows)
    payload = {
        "recipient": recipient,
        "subject": subject,
        "html": html,
        "rows": rows,
    }
    key = f"confirmacion:{round_number}:{recipient}:{fingerprint}"
    return enqueue(db, key, "confirmacion", round_number, player_id, payload)


def enqueue_all_predicted(
    db,
    recipient: str,
    player_id: int,
    round_number: int,
    matches: list[dict],
    *,
    enqueue=enqueue_notification,
) -> bool:
    """Queue the round reveal for one player using an idempotent player key."""
    subject, html = render_todos_predijeron(round_number, matches)
    payload = {"recipient": recipient, "subject": subject, "html": html, "matches": matches}
    key = f"todos_predijeron:{round_number}:{player_id}"
    return enqueue(db, key, "todos_predijeron", round_number, player_id, payload)


def _enqueue_player_event(db, kind, recipient, player_id, round_number, subject, html, data, enqueue):
    payload = {"recipient": recipient, "subject": subject, "html": html, **data}
    return enqueue(db, f"{kind}:{round_number}:{player_id}", kind, round_number, player_id, payload)


def enqueue_reminder_60min(db, recipient, player_id, player_name, round_number, matches, top3, in_top3, *, enqueue=enqueue_notification):
    subject, html = render_recordatorio_60min(player_name, round_number, matches, top3, in_top3)
    return _enqueue_player_event(db, "recordatorio_60min", recipient, player_id, round_number, subject, html,
                                 {"matches": matches}, enqueue)


def enqueue_missing_predictions_reminder(db, recipient, player_id, player_name, round_number, matches, total_matches, *, enqueue=enqueue_notification):
    subject, html = render_recordatorio_faltantes(player_name, round_number, matches, total_matches)
    return _enqueue_player_event(db, "recordatorio_faltantes", recipient, player_id, round_number, subject, html,
                                 {"matches": matches}, enqueue)


def enqueue_round_finished(db, recipient, player_id, player_name, round_number, results, ranking, *, enqueue=enqueue_notification):
    subject, html = render_fecha_terminada(player_name, round_number, results, ranking)
    return _enqueue_player_event(db, "fecha_terminada", recipient, player_id, round_number, subject, html,
                                 {"results": results, "ranking": ranking}, enqueue)


def enqueue_polla_finished(db, recipient, player_id, last_round_number, polla_number, start_round, end_round, top5, *, enqueue=enqueue_notification):
    """Un solo correo por jugador anunciando al/los ganador(es) de la polla
    (bloque de 5 fechas) que se acaba de completar. Se clava a last_round_number
    (el fin del rango) para reusar el mismo candado de idempotencia que el
    resto de eventos por fecha."""
    subject, html = render_ganadores_polla(polla_number, start_round, end_round, top5)
    return _enqueue_player_event(db, "polla_terminada", recipient, player_id, last_round_number, subject, html,
                                 {"polla_number": polla_number, "top5": top5}, enqueue)
