from core.scoring import score_display


def test_exact_score_breaks_two_total_points_into_exact_and_result_components():
    display = score_display(2, True)

    assert display.label == "Exacto +1 · G/E/P +1 · Total +2"
    assert display.css_class == "polla-pill--exacto"
    assert (display.total_points, display.exact_points, display.result_points) == (2, 1, 1)


def test_non_exact_correct_result_only_awards_the_result_component():
    display = score_display(1, False)

    assert display.label == "G/E/P +1"
    assert (display.total_points, display.exact_points, display.result_points) == (1, 0, 1)


def test_failed_score_awards_no_components():
    display = score_display(0, False)

    assert display.label == "Fallo · +0"
    assert (display.total_points, display.exact_points, display.result_points) == (0, 0, 0)


def test_pending_score_is_explicit():
    assert score_display(None, None).label == "Pendiente"
