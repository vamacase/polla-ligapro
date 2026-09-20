from core.results_view import render_resultado


def test_resultado_mantiene_cada_gol_junto_al_equipo_en_orden_local_visitante():
    html = render_resultado("Emelec", "", 1, 2, "Libertad FC", "")

    assert 'aria-label="Marcador final: Emelec 1, Libertad FC 2"' in html
    assert '<span class="polla-score-team polla-score-team--local"><span class="polla-score-name">Emelec</span></span>' in html
    assert ('<span class="polla-score-pair"><span class="polla-score">1</span>'
            '<span class="polla-score-separator" aria-hidden="true">–</span>'
            '<span class="polla-score">2</span></span>') in html
    assert '<span class="polla-score-team polla-score-team--visita"><span class="polla-score-name">Libertad FC</span></span>' in html


def test_resultado_escapa_nombres_de_equipo_para_insertarlos_en_html():
    html = render_resultado("A&B", "", 0, 0, "Visitante", "")

    assert "A&amp;B" in html
    assert "A&B" not in html
