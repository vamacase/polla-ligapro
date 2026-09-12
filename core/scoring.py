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
