import sys
from types import ModuleType

import pytest

import db
from services.auth import hash_pin, read_session, sign_session, validar_pin, verify_pin


def test_client_rejects_missing_service_key(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "deprecated-public-key")
    monkeypatch.setattr(db, "RAIZ", tmp_path)
    streamlit = ModuleType("streamlit")
    streamlit.secrets = {}
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)

    def create_client_must_not_run(*_args, **_kwargs):
        raise AssertionError("create_client must not receive SUPABASE_KEY")

    monkeypatch.setattr(db, "create_client", create_client_must_not_run)

    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_KEY"):
        db.get_client()


def test_client_loads_project_dotenv_for_local_scripts(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(db, "RAIZ", tmp_path)
    (tmp_path / ".env").write_text(
        "SUPABASE_URL=https://example.supabase.co\n"
        "SUPABASE_SERVICE_KEY=service-role-key\n",
        encoding="utf-8",
    )

    client = db.get_client()

    assert client is not None


def test_pin_hash_uses_scrypt_and_verifies_only_the_right_value():
    encoded = hash_pin("1234")
    assert encoded.startswith("scrypt$16384$8$1$")
    assert verify_pin("1234", encoded)
    assert not verify_pin("9999", encoded)


def test_pin_hash_handles_values_in_the_required_encoding_prefix():
    encoded = hash_pin("scrypt")
    assert verify_pin("scrypt", encoded)


def test_session_rejects_tampering_and_expiry():
    token = sign_session(7, 3, 2_000, "test-secret")
    assert read_session(token, "test-secret", 1_999) == (7, 3)
    assert read_session(token + "x", "test-secret", 1_999) is None
    assert read_session(token, "test-secret", 2_000) is None


def test_session_payload_carries_player_and_session_version():
    token = sign_session(9, 4, 9_999, "test-secret")
    assert read_session(token, "test-secret", 100) == (9, 4)


def test_player_pin_requires_exactly_four_ascii_digits():
    assert validar_pin("0042")
    assert not validar_pin("123")
    assert not validar_pin("12345")
    assert not validar_pin("12a4")
