from core.scoring import add_score_to_ranking, ranking_email_breakdown, score_display


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


def test_ranking_aggregation_counts_exact_as_one_exact_and_one_result():
    aggregate = {"puntos_totales": 0, "aciertos_exactos": 0, "aciertos_1x2": 0}

    assert add_score_to_ranking(aggregate, points=2, exact=True) == {
        "puntos_totales": 2,
        "aciertos_exactos": 1,
        "aciertos_1x2": 1,
    }


def test_ranking_aggregation_counts_non_exact_result_and_failure_components():
    aggregate = {"puntos_totales": 0, "aciertos_exactos": 0, "aciertos_1x2": 0}

    after_result = add_score_to_ranking(aggregate, points=1, exact=False)
    after_failure = add_score_to_ranking(aggregate, points=0, exact=False)

    assert after_result == {"puntos_totales": 1, "aciertos_exactos": 0, "aciertos_1x2": 1}
    assert after_failure == {"puntos_totales": 0, "aciertos_exactos": 0, "aciertos_1x2": 0}


def test_email_breakdown_assigns_one_exact_point_and_one_result_point_for_an_exact_score():
    assert ranking_email_breakdown(total_points=2, exact_count=1) == (1, 1)
