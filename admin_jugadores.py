"""
ADMIN — alta de jugadores de la polla.

Uso:
    python admin_jugadores.py agregar "Nombre Apellido" 1234 [--prod]
    python admin_jugadores.py listar [--prod]

Por defecto usa .env (base de DESARROLLO). Agregar --prod para operar sobre
la polla REAL (usa .env.prod).
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

ES_PROD = "--prod" in sys.argv
if ES_PROD:
    sys.argv.remove("--prod")

ARCHIVO_ENV = ".env.prod" if ES_PROD else ".env"
load_dotenv(Path(__file__).resolve().parent / ARCHIVO_ENV)
print(f"[ambiente: {'PRODUCCIÓN' if ES_PROD else 'desarrollo'} — {ARCHIVO_ENV}]")
from db import get_client  # noqa: E402


def agregar(nombre: str, pin: str):
    db = get_client()
    db.table("jugadores").upsert({"nombre": nombre, "pin": pin}, on_conflict="nombre").execute()
    print(f"[ok] {nombre} (PIN {pin})")


def listar():
    db = get_client()
    for j in db.table("jugadores").select("nombre, pin").order("nombre").execute().data:
        print(f"  {j['nombre']:20s} PIN {j['pin']}")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "agregar":
        agregar(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == "listar":
        listar()
    else:
        print(__doc__)
