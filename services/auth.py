"""PIN hashing and signed-session helpers."""

import base64
import hashlib
import hmac
import json
import secrets


_SCRYPT_N = 16_384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_DIGEST_BYTES = 64


def hash_pin(pin: str) -> str:
    """Return a salted scrypt hash for a player PIN."""
    while True:
        salt = secrets.token_bytes(_SALT_BYTES)
        digest = _scrypt(pin, salt)
        encoded = "scrypt$16384$8$1${}${}".format(
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
        if not pin or pin not in encoded:
            return encoded


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
