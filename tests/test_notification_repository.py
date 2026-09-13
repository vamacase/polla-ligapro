from repositories.notifications import notification_key


def test_notification_key_is_stable_per_player_round_and_kind():
    assert notification_key("fecha_terminada", 30, 7) == "fecha_terminada:30:7"
    assert notification_key("fecha_terminada", 30, 7) != notification_key(
        "fecha_terminada", 30, 8
    )
