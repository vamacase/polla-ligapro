"""HTML helpers for compact, unambiguous match-result presentation."""

from html import escape


def render_resultado(local: str, logo_local: str, goles_local: int,
                     goles_visita: int, visita: str, logo_visita: str) -> str:
    """Render escudo local, marcador y escudo visitante sin nombres visibles."""
    nombre_local = escape(str(local))
    nombre_visita = escape(str(visita))
    gl, gv = int(goles_local), int(goles_visita)
    if gl > gv:
        detalle_resultado = f"Ganador: {nombre_local}"
        clase_local, clase_visita = " polla-score--ganador", ""
    elif gv > gl:
        detalle_resultado = f"Ganador: {nombre_visita}"
        clase_local, clase_visita = "", " polla-score--ganador"
    else:
        detalle_resultado = "Empate"
        clase_local = clase_visita = ""
    return (
        f'<div class="polla-scoreline" role="img" aria-label="Marcador final: '
        f'{nombre_local} {gl}, {nombre_visita} {gv}. {detalle_resultado}">'
        f'<span class="polla-score-team polla-score-team--local" aria-hidden="true">'
        f'{logo_local}</span>'
        f'<span class="polla-score-pair" aria-hidden="true">'
        f'<span class="polla-score{clase_local}">{gl}</span>'
        f'<span class="polla-score-separator" aria-hidden="true">–</span>'
        f'<span class="polla-score{clase_visita}">{gv}</span></span>'
        f'<span class="polla-score-team polla-score-team--visita" aria-hidden="true">'
        f'{logo_visita}</span>'
        f'</div>'
    )
