from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreDisplay:
    label: str
    css_class: str
    total_points: int | None
    exact_points: int | None
    result_points: int | None


def score_display(points: int | None, exact: bool | None) -> ScoreDisplay:
    if points is None:
        return ScoreDisplay("Pendiente", "polla-pill--na", None, None, None)
    if points == 2 and exact:
        return ScoreDisplay("Exacto +1 · G/E/P +1 · Total +2", "polla-pill--exacto", 2, 1, 1)
    if points == 1 and not exact:
        return ScoreDisplay("G/E/P +1", "polla-pill--1x2", 1, 0, 1)
    return ScoreDisplay("Fallo · +0", "polla-pill--fallo", 0, 0, 0)


def add_score_to_ranking(aggregate: dict[str, int], *, points: int, exact: bool) -> dict[str, int]:
    """Return a ranking aggregate with one scored prediction added."""
    display = score_display(points, exact)
    return {
        **aggregate,
        "puntos_totales": aggregate["puntos_totales"] + display.total_points,
        "aciertos_exactos": aggregate["aciertos_exactos"] + display.exact_points,
        "aciertos_1x2": aggregate["aciertos_1x2"] + display.result_points,
    }


def ranking_email_breakdown(total_points: int, exact_count: int) -> tuple[int, int]:
    """Split a ranking total into Exacto and G/E/P point components."""
    return exact_count, total_points - exact_count
