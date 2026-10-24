from email_notif import render_todos_predijeron


def test_reveal_names_players_who_missed_the_match():
    _, html = render_todos_predijeron(34, [{
        "local": "Independiente del Valle", "visita": "Universidad Católica",
        "grupos": {
            "local": [{"nombre": "Vicente Macas", "gl": 2, "gv": 1}],
            "empate": [], "visita": [],
        },
        "total_jugadores": 3,
        "sin_prediccion": ["Juan Carlos Herrera", "Regulo Viscarra"],
    }])

    assert "Juan Carlos Herrera" in html
    assert "Regulo Viscarra" in html
    assert "1 de 3" in html
    assert "Sin predicción (2)" in html


def test_complete_match_does_not_show_an_empty_missing_group():
    _, html = render_todos_predijeron(34, [{
        "local": "Manta", "visita": "Cuenca",
        "grupos": {
            "local": [], "empate": [{"nombre": "Vicente", "gl": 0, "gv": 0}],
            "visita": [],
        },
        "total_jugadores": 1, "sin_prediccion": [],
    }])

    assert "1 de 1" in html
    assert "Sin predicción" not in html


def test_match_with_no_predictions_still_lists_every_missing_player():
    _, html = render_todos_predijeron(34, [{
        "local": "Manta", "visita": "Cuenca",
        "grupos": {"local": [], "empate": [], "visita": []},
        "total_jugadores": 2, "sin_prediccion": ["Ana & Luis", "María <Pérez>"],
    }])

    assert "0 de 2" in html
    assert "Ana &amp; Luis" in html
    assert "María &lt;Pérez&gt;" in html


def test_missing_players_are_calculated_separately_for_each_match():
    from services.notification_payloads import build_reveal_matches

    matches = [
        {"id": 11, "local": "IDV", "visita": "Católica"},
        {"id": 12, "local": "Manta", "visita": "Cuenca"},
    ]
    players = [
        {"id": 1, "nombre": "Ana", "email": None},
        {"id": 2, "nombre": "Luis", "email": "luis@example.test"},
        {"id": 3, "nombre": "María", "email": "maria@example.test"},
    ]
    predictions = [
        {"partido_id": 11, "jugador_id": 1, "gl_pred": 0, "gv_pred": 0},
        {"partido_id": 12, "jugador_id": 2, "gl_pred": 0, "gv_pred": 1, "es_exacto": True},
        {"partido_id": 12, "jugador_id": 3, "gl_pred": 1, "gv_pred": 0},
    ]

    result = build_reveal_matches(matches, players, predictions)

    assert result[0]["sin_prediccion"] == ["Luis", "María"]
    assert result[1]["sin_prediccion"] == ["Ana"]
    assert result[0]["total_jugadores"] == result[1]["total_jugadores"] == 3
    assert result[0]["grupos"]["empate"] == [
        {"nombre": "Ana", "gl": 0, "gv": 0, "es_exacto": False},
    ]
    assert result[1]["grupos"]["visita"] == [
        {"nombre": "Luis", "gl": 0, "gv": 1, "es_exacto": True},
    ]
