from services.notification_payloads import enqueue_confirmation


def test_confirmation_is_enqueued_with_a_stable_key():
    captured = {}

    def fake_enqueue(db, key, kind, round_number, player_id, payload):
        captured.update(key=key, kind=kind, round_number=round_number, payload=payload)
        return True

    accepted = enqueue_confirmation(
        object(),
        "ana@example.test",
        "Ana",
        30,
        [{"local": "Manta", "visita": "Aucas", "gl": 2, "gv": 1}],
        enqueue=fake_enqueue,
    )

    assert accepted is True
    assert captured["key"].startswith("confirmacion:30:ana@example.test:")
    assert captured["kind"] == "confirmacion"
    assert captured["payload"]["rows"][0]["gl"] == 2
