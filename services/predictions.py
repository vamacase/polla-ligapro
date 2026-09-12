"""Database-backed prediction saving and deadline maintenance."""

from datetime import datetime

from core.deadlines import DeadlineMatch, calculate_deadlines


def save_prediction(client, player_id: int, match_id: int, local_goals: int, away_goals: int) -> dict:
    """Persist one prediction through the server-clock-validated RPC."""
    result = client.rpc(
        "guardar_prediccion_segura",
        {
            "p_jugador_id": player_id,
            "p_partido_id": match_id,
            "p_gl_pred": int(local_goals),
            "p_gv_pred": int(away_goals),
        },
    ).execute()
    if not result.data:
        raise RuntimeError("La base no devolvió la predicción guardada.")
    return result.data[0]


def refresh_round_deadlines(client, round_number: int) -> int:
    """Recalculate every deadline in one round after a fixture refresh."""
    rows = (
        client.table("partidos").select("id,kickoff")
        .eq("fecha_ronda", round_number).execute().data
        or []
    )
    deadlines = calculate_deadlines(
        [
            DeadlineMatch(
                row["id"],
                datetime.fromisoformat(row["kickoff"].replace("Z", "+00:00")),
            )
            for row in rows
        ]
    )
    for match_id, deadline in deadlines.items():
        client.table("partidos").update(
            {"cierre_predicciones": deadline.isoformat()}
        ).eq("id", match_id).execute()
    return len(deadlines)
