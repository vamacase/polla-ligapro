from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreDisplay:
    label: str
    css_class: str


def score_display(points: int | None, exact: bool | None) -> ScoreDisplay:
    if points is None:
        return ScoreDisplay("Pendiente", "polla-pill--na")
    if points == 2 and exact:
        return ScoreDisplay("Exacto · +2", "polla-pill--exacto")
    if points == 1 and not exact:
        return ScoreDisplay("1X2 · +1", "polla-pill--1x2")
    return ScoreDisplay("Fallo · +0", "polla-pill--fallo")
