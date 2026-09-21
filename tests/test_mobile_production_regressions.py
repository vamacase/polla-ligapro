from pathlib import Path


APP = (Path(__file__).parents[1] / "app" / "app.py").read_text(encoding="utf-8")


def test_mobile_css_is_injected_through_markdown_compatible_style_path():
    assert 'st.markdown("""' in APP
    assert "unsafe_allow_html=True" in APP
    assert 'div[data-testid="stTabs"] [role="tablist"]' in APP
    assert "position:fixed" in APP


def test_result_renderer_module_is_reloaded_with_app_code():
    assert "importlib.reload(results_view)" in APP
    assert "render_resultado = results_view.render_resultado" in APP
