from core.scoring import score_display


def test_exact_score_is_two_points_and_uses_exact_label():
    assert score_display(2, True).label == "Exacto · +2"


def test_1x2_score_has_its_own_label():
    assert score_display(1, False).label == "1X2 · +1"


def test_pending_and_failed_scores_are_explicit():
    assert score_display(None, None).label == "Pendiente"
    assert score_display(0, False).label == "Fallo · +0"
