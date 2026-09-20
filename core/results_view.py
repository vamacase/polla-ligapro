"""HTML helpers for compact, unambiguous match-result presentation."""

from html import escape


def render_resultado(local: str, logo_local: str, goles_local: int,
                     goles_visita: int, visita: str, logo_visita: str) -> str:
    """Render a conventional home-score / away-score line for narrow screens."""
    nombre_local = escape(str(local))
    nombre_visita = escape(str(visita))
    return (
        f'<div class="polla-scoreline" aria-label="Marcador final: '
        f'{nombre_local} {goles_local}, {nombre_visita} {goles_visita}">'
        f'<span class="polla-score-team polla-score-team--local">'
        f'<span class="polla-score-name">{nombre_local}</span>{logo_local}</span>'
        f'<span class="polla-score-pair"><span class="polla-score">{goles_local}</span>'
        f'<span class="polla-score-separator" aria-hidden="true">–</span>'
        f'<span class="polla-score">{goles_visita}</span></span>'
        f'<span class="polla-score-team polla-score-team--visita">'
        f'{logo_visita}<span class="polla-score-name">{nombre_visita}</span></span>'
        f'</div>'
    )
