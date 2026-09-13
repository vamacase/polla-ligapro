from services.notification_payloads import (
    enqueue_all_predicted, enqueue_confirmation, enqueue_missing_predictions_reminder,
    enqueue_reminder_60min, enqueue_round_finished,
)


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


def test_round_reveal_is_enqueued_once_per_player():
    captured = {}

    def fake_enqueue(db, key, kind, round_number, player_id, payload):
        captured.update(key=key, kind=kind, round_number=round_number, player_id=player_id, payload=payload)
        return True

    enqueue_all_predicted(
        object(), "ana@example.test", 8, 30,
        [{"local": "Manta", "visita": "Aucas", "grupos": {"local": [], "empate": [], "visita": []}}],
        enqueue=fake_enqueue,
    )

    assert captured["key"] == "todos_predijeron:30:8"
    assert captured["kind"] == "todos_predijeron"
    assert captured["payload"]["matches"][0]["local"] == "Manta"


def test_sync_notifications_use_the_player_idempotency_key():
    captured = []

    def fake_enqueue(db, key, kind, round_number, player_id, payload):
        captured.append((key, kind, round_number, player_id, payload))
        return True

    matches = [{"local": "Manta", "visita": "Aucas", "hora": "18:00"}]
    enqueue_reminder_60min(object(), "ana@example.test", 8, "Ana", 30, matches, [], False, enqueue=fake_enqueue)
    enqueue_missing_predictions_reminder(object(), "ana@example.test", 8, "Ana", 30, matches, 8, enqueue=fake_enqueue)
    enqueue_round_finished(object(), "ana@example.test", 8, "Ana", 30, [], [], enqueue=fake_enqueue)

    assert [item[0] for item in captured] == [
        "recordatorio_60min:30:8", "recordatorio_faltantes:30:8", "fecha_terminada:30:8",
    ]
    assert all(item[4]["recipient"] == "ana@example.test" for item in captured)
