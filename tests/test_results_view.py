from core.results_view import render_resultado


def test_resultado_muestra_escudos_marcador_y_ganador_sin_nombres_visibles():
    escudo_local = '<img data-equipo="local" alt="">'
    escudo_visita = '<img data-equipo="visita" alt="">'
    html = render_resultado("Emelec", escudo_local, 1, 2, "Libertad FC", escudo_visita)

    assert 'role="img" aria-label="Marcador final: Emelec 1, Libertad FC 2. Ganador: Libertad FC"' in html
    assert html.index(escudo_local) < html.index('class="polla-score-pair"') < html.index(escudo_visita)
    assert '<span class="polla-score">1</span>' in html
    assert '<span class="polla-score polla-score--ganador">2</span>' in html
    assert "polla-score-name" not in html


def test_resultado_empatado_no_resalta_a_ningun_ganador():
    html = render_resultado("Local", "", 1, 1, "Visita", "")

    assert 'aria-label="Marcador final: Local 1, Visita 1. Empate"' in html
    assert "polla-score--ganador" not in html


def test_resultado_escapa_nombres_de_equipo_para_insertarlos_en_html():
    html = render_resultado("A&B", "", 0, 0, "Visitante", "")

    assert "A&amp;B" in html
    assert "A&B" not in html
