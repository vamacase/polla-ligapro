"""Migra PINs existentes a hashes scrypt sin revelar sus valores."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import get_client
from services.auth import hash_pin


def migrate_pin_hashes(client=None) -> int:
    """Actualiza solamente ``pin_hash`` y devuelve el número de jugadores."""
    if client is None:
        client = get_client()
    players = client.table("jugadores").select("id,pin").execute().data or []

    if any(player.get("pin") is None for player in players):
        raise RuntimeError("Migración cancelada: hay jugadores sin PIN.")

    for player in players:
        client.table("jugadores").update(
            {"pin_hash": hash_pin(str(player["pin"]))}
        ).eq("id", player["id"]).execute()

    return len(players)


if __name__ == "__main__":
    migrated = migrate_pin_hashes()
    print(f"Hashes de PIN migrados: {migrated}")
