"""PIN hashing and signed-session helpers."""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone


_SCRYPT_N = 16_384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_DIGEST_BYTES = 64


def hash_pin(pin: str) -> str:
    """Return a salted scrypt hash for a player PIN."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _scrypt(pin, salt)
    return "scrypt$16384$8$1${}${}".format(
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_pin(pin: str, encoded: str) -> bool:
    """Return whether *pin* matches an encoded scrypt hash."""
    try:
        algorithm, n, r, p, salt_encoded, digest_encoded = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1"):
            return False
        salt = base64.b64decode(salt_encoded, validate=True)
        expected = base64.b64decode(digest_encoded, validate=True)
        actual = _scrypt(pin, salt)
        return hmac.compare_digest(actual, expected)
    except (AttributeError, ValueError, TypeError):
        return False


def sign_session(player_id: int, version: int, expires_at: int, secret: str) -> str:
    """Return a URL-safe, HMAC-SHA256 signed player-session token."""
    payload = json.dumps(
        {"p": player_id, "v": version, "e": expires_at},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded_payload = _urlsafe_b64encode(payload)
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{encoded_payload}.{_urlsafe_b64encode(signature)}"


def read_session(token: str, secret: str, now: int) -> tuple[int, int] | None:
    """Return player id and session version when a token is valid and current."""
    try:
        encoded_payload, encoded_signature = token.split(".")
        payload = _urlsafe_b64decode(encoded_payload)
        supplied_signature = _urlsafe_b64decode(encoded_signature)
        expected_signature = hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None

        session = json.loads(payload)
        player_id = session["p"]
        version = session["v"]
        expires_at = session["e"]
        if (
            type(player_id) is not int
            or type(version) is not int
            or type(expires_at) is not int
            or expires_at <= now
        ):
            return None
        return player_id, version
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


def _scrypt(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DIGEST_BYTES,
    )


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _urlsafe_b64decode(value: str) -> bytes:
    return base64.b64decode(value, altchars=b"-_", validate=True)


def validar_pin(pin: str) -> bool:
    """Player PINs contain exactly four ASCII digits, including leading zeroes."""
    return isinstance(pin, str) and len(pin) == 4 and all(c in "0123456789" for c in pin)


def jugador_de_sesion(client, token: str, secret: str, now: int):
    """Validate the signature, expiry and current database revocation version."""
    session = read_session(token, secret, now)
    if session is None:
        return None
    player_id, version = session
    rows = (client.table("jugadores").select("id,nombre,session_version")
            .eq("id", player_id).eq("session_version", version).execute().data)
    return rows[0] if rows else None


def autenticar_jugador(client, nombre: str, pin: str, now=None):
    return _autenticar(client, "nombre", nombre, pin, now)


def _autenticar(client, campo, valor, pin, now=None):
    """Persist failures with compare-and-swap so concurrent requests cannot lose them."""
    now = now or datetime.now(timezone.utc)
    columns = "id,nombre,pin_hash,session_version,fallos_pin,bloqueado_hasta"
    for _ in range(5):
        rows = client.table("jugadores").select(columns).eq(campo, valor).execute().data
        if not rows:
            return None
        player = rows[0]
        until_raw = player["bloqueado_hasta"]
        until = datetime.fromisoformat(until_raw) if until_raw else None
        if until and until > now:
            return None
        success = validar_pin(pin) and verify_pin(pin, player["pin_hash"])
        failures = 0 if until else player["fallos_pin"]
        failures = 0 if success else failures + 1
        blocked_until = (now + timedelta(minutes=15)).isoformat() if failures >= 5 else None
        query = (client.table("jugadores")
                 .update({"fallos_pin": failures, "bloqueado_hasta": blocked_until})
                 .eq("id", player["id"]).eq("session_version", player["session_version"])
                 .eq("fallos_pin", player["fallos_pin"]))
        query = (query.is_("bloqueado_hasta", "null") if until_raw is None
                 else query.eq("bloqueado_hasta", until_raw))
        if query.execute().data:
            return ({key: player[key] for key in ("id", "nombre", "session_version")}
                    if success else None)
    # Contention must never authenticate using a stale credential snapshot.
    return None


def reemplazar_pin(client, player, pin: str):
    """Reset a PIN and revoke every prior session using a version-checked update."""
    if not validar_pin(pin):
        raise ValueError("El PIN debe tener cuatro dígitos.")
    rows = (client.table("jugadores").update({
        "pin_hash": hash_pin(pin), "session_version": player["session_version"] + 1,
        "fallos_pin": 0, "bloqueado_hasta": None,
    }).eq("id", player["id"]).eq("session_version", player["session_version"])
        .execute().data)
    if not rows:
        return None
    return {key: rows[0][key] for key in ("id", "nombre", "session_version")}


def cambiar_pin(client, player_id: int, actual: str, nuevo: str, now=None):
    if not validar_pin(nuevo):
        raise ValueError("El PIN debe tener cuatro dígitos.")
    player = _autenticar(client, "id", player_id, actual, now)
    return reemplazar_pin(client, player, nuevo) if player else None
