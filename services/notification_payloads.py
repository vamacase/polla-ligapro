"""Payload construction for notification jobs; this module never sends SMTP."""

from hashlib import sha256
import json

from email_notif import render_confirmacion, render_todos_predijeron
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
