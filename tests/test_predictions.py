from services.predictions import save_prediction


class FakeClient:
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
        return type("Result", (), {"data": [{"id": 99}]})()


def test_save_prediction_uses_atomic_rpc():
    assert save_prediction(FakeClient(), 1, 8, 2, 0) == {"id": 99}
