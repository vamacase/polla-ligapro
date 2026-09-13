"""Durable notification outbox persistence."""


def notification_key(kind: str, round_number: int, player_id: int) -> str:
    """Build the deterministic key used to deduplicate a player event."""
    return f"{kind}:{round_number}:{player_id}"


def enqueue_notification(db, key: str, kind: str, round_number: int, player_id, payload: dict) -> bool:
    """Add work to the outbox, returning false when its key already exists."""
    recipient = payload.get("recipient")
    if not recipient:
        raise ValueError("El payload de notificación requiere destinatario.")
    result = db.table("notificaciones").upsert(
        {
            "clave": key,
            "tipo": kind,
            "fecha_ronda": round_number,
            "jugador_id": player_id,
            "destinatario": recipient,
            "payload": payload,
        },
        on_conflict="clave",
        ignore_duplicates=True,
    ).execute()
    return bool(result.data)
