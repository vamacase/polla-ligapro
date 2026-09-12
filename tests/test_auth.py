from services.auth import hash_pin, read_session, sign_session, verify_pin


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
