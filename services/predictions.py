"""Database-backed prediction saving and deadline maintenance."""

from datetime import datetime

from core.deadlines import DeadlineMatch, calculate_deadlines


def save_prediction(client, player_id: int, match_id: int, local_goals: int, away_goals: int) -> dict:
    """Persist one prediction through the server-clock-validated RPC.

    guardar_prediccion_segura() está declarado `returns predicciones`
    (rowtype escalar, no `setof`) — postgrest-py entrega ese resultado
    como un dict plano, no como lista de una fila. Indexar con [0] revienta
    con KeyError en TODO guardado exitoso (bug real visto en producción).
    """
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
    return result.data[0] if isinstance(result.data, list) else result.data


def refresh_round_deadlines(client, round_number: int) -> int:
    """Recalculate every deadline in one round after a fixture refresh.

    Un partido anulado=true (reprogramado sin fecha firme, ver README) nunca
    otorga puntos y puede conservar un kickoff viejo de cuando sí tenía
    fecha -- si cuenta para el orden 1°/2°, desplaza al verdadero 2° partido
    real y le hereda un cierre más temprano del que le corresponde (bug real
    visto en Fecha 32: Barcelona-IDV, anulado con kickoff del 21/09, empujó
    el cierre de Delfín vs Mushuc Runa de su propio kickoff a las 13:00).
    Se excluye del cálculo igual que ya se hace en sync_fixture()."""
    rows = (
        client.table("partidos").select("id,kickoff,anulado")
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
            if not row["anulado"]
        ]
    )
    for match_id, deadline in deadlines.items():
        client.table("partidos").update(
            {"cierre_predicciones": deadline.isoformat()}
        ).eq("id", match_id).execute()
    return len(deadlines)
