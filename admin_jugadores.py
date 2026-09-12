"""
ADMIN — alta de jugadores de la polla.

Uso:
    python admin_jugadores.py agregar "Nombre Apellido" [--prod]
    python admin_jugadores.py listar [--prod]

Por defecto usa .env (base de DESARROLLO). Agregar --prod para operar sobre
la polla REAL (usa .env.prod).
"""
import argparse
from getpass import getpass
from pathlib import Path
from dotenv import load_dotenv

from db import get_client
from services.auth import hash_pin, reemplazar_pin, validar_pin


def agregar(nombre: str, pin: str):
    if not validar_pin(pin):
        raise ValueError("El PIN debe tener cuatro dígitos.")
    db = get_client()
    existentes = (db.table("jugadores").select("id,nombre,session_version")
                  .eq("nombre", nombre).execute().data)
    if existentes:
        if not reemplazar_pin(db, existentes[0], pin):
            raise RuntimeError("El jugador cambió durante la operación; vuelve a intentarlo.")
    else:
        db.table("jugadores").insert({"nombre": nombre, "pin_hash": hash_pin(pin)}).execute()
    print(f"[ok] {nombre}")


def listar():
    db = get_client()
    for j in db.table("jugadores").select("nombre,email").order("nombre").execute().data:
        print(f"  {j['nombre']:20s} {j['email'] or ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("agregar", "listar"))
    parser.add_argument("nombre", nargs="?")
    parser.add_argument("--prod", action="store_true")
    args = parser.parse_args()
    if args.accion == "agregar" and not args.nombre:
        parser.error("agregar requiere el nombre del jugador")
    archivo_env = ".env.prod" if args.prod else ".env"
    load_dotenv(Path(__file__).resolve().parent / archivo_env)
    print(f"[ambiente: {'PRODUCCIÓN' if args.prod else 'desarrollo'} — {archivo_env}]")
    if args.accion == "agregar":
        pin = getpass("PIN de cuatro dígitos: ")
        if pin != getpass("Repite el PIN: "):
            parser.error("Los PIN no coinciden")
        agregar(args.nombre, pin)
    else:
        listar()


if __name__ == "__main__":
    main()
