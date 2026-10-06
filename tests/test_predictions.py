from services.predictions import refresh_round_deadlines, save_prediction


class FakeClient:
    def __init__(self, data):
        self._data = data

    def rpc(self, name, payload):
        assert name == "guardar_prediccion_segura"
        assert payload == {
            "p_jugador_id": 1,
            "p_partido_id": 8,
            "p_gl_pred": 2,
            "p_gv_pred": 0,
        }
        return self

    def execute(self):
        return type("Result", (), {"data": self._data})()


def test_save_prediction_uses_atomic_rpc():
    # Forma real que devuelve postgrest-py para un RPC `returns predicciones`
    # (rowtype escalar, no setof): un dict plano, no una lista de una fila.
    assert save_prediction(FakeClient({"id": 99}), 1, 8, 2, 0) == {"id": 99}


def test_save_prediction_accepts_list_shape_too():
    # Por si una versión distinta de postgrest-py sí envuelve en lista.
    assert save_prediction(FakeClient([{"id": 99}]), 1, 8, 2, 0) == {"id": 99}


class _FakeTable:
    def __init__(self, rows, updates):
        self._rows = rows
        self._updates = updates
        self._filters = {}
        self._pending_update = None

    def select(self, _cols):
        return self

    def update(self, data):
        self._pending_update = data
        return self

    def eq(self, col, value):
        self._filters[col] = value
        return self

    def execute(self):
        if self._pending_update is not None:
            (match_id,) = self._filters.values()
            self._updates[match_id] = self._pending_update["cierre_predicciones"]
            self._pending_update = None
            return type("Result", (), {"data": [{"id": match_id}]})()
        (round_number,) = self._filters.values()
        data = [r for r in self._rows if r["fecha_ronda"] == round_number]
        return type("Result", (), {"data": data})()


class FakeDeadlinesClient:
    def __init__(self, rows):
        self._rows = rows
        self.updates = {}

    def table(self, _name):
        return _FakeTable(self._rows, self.updates)


def test_refresh_round_deadlines_excludes_anulado_from_1st_2nd():
    # Un partido anulado=true (reprogramado sin fecha firme) puede conservar
    # un kickoff viejo -- si cuenta para el orden 1°/2°, desplaza al verdadero
    # 2° partido real y le hereda un cierre más temprano del que le toca
    # (bug real: Fecha 32, Barcelona-IDV anulado con kickoff del 21/09 empujó
    # el cierre de Delfín vs Mushuc Runa a las 13:00 en vez de su propio
    # kickoff 15:30).
    rows = [
        {"id": 1, "fecha_ronda": 32, "kickoff": "2026-09-21T19:30:00+00:00", "anulado": True},
        {"id": 2, "fecha_ronda": 32, "kickoff": "2026-10-09T18:00:00+00:00", "anulado": False},
        {"id": 3, "fecha_ronda": 32, "kickoff": "2026-10-09T20:30:00+00:00", "anulado": False},
        {"id": 4, "fecha_ronda": 32, "kickoff": "2026-10-10T16:30:00+00:00", "anulado": False},
    ]
    client = FakeDeadlinesClient(rows)
    n = refresh_round_deadlines(client, 32)

    assert n == 3  # el anulado queda fuera del cálculo
    assert 1 not in client.updates  # y no recibe un cierre nuevo
    assert client.updates[2] == "2026-10-09T18:00:00+00:00"  # 1° real: su propio kickoff
    assert client.updates[3] == "2026-10-09T20:30:00+00:00"  # 2° real: su propio kickoff
    assert client.updates[4] == "2026-10-09T20:30:00+00:00"  # 3°+: al kickoff del 2°
