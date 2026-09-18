from services.predictions import save_prediction


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
