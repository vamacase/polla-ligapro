# Puntaje coherente y pruebas base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar y calcular de forma verificable 2 puntos por marcador exacto, 1 por 1X2 y 0 por fallo.

**Architecture:** La vista SQL `v_puntos` conserva el cálculo de producción. Un módulo Python puro centraliza etiquetas de resultado para la app y evita textos contradictorios; sus pruebas no necesitan Streamlit ni Supabase.

**Tech Stack:** Python 3.14, pytest 8, Streamlit, Supabase/Postgres.

**Spec:** `docs/superpowers/specs/2026-09-11-estabilizacion-polla-ligapro-design.md`

## Global Constraints

- No modificar predicciones ni resultados existentes.
- Marcador exacto = 2; 1X2 correcto no exacto = 1; fallo = 0.
- Las pruebas unitarias no contactan Supabase, Gmail ni SofaScore.
- Todo texto visible y README debe usar la misma regla.

---

### Task 1: Crear la base de pruebas y el contrato de puntaje

**Files:**
- Modify: `requirements.txt`
- Create: `core/__init__.py`
- Create: `core/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Produces: `ScoreDisplay(label: str, css_class: str)` y `score_display(points: int | None, exact: bool | None) -> ScoreDisplay`.
- Produces: una suite `pytest` ejecutable con `pytest -q`.

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
from core.scoring import score_display

def test_exact_score_is_two_points_and_uses_exact_label():
    assert score_display(2, True).label == "Exacto · +2"

def test_1x2_score_has_its_own_label():
    assert score_display(1, False).label == "1X2 · +1"

def test_pending_and_failed_scores_are_explicit():
    assert score_display(None, None).label == "Pendiente"
    assert score_display(0, False).label == "Fallo · +0"
```

- [ ] **Step 2: Ejecutar la prueba para comprobar que falla**

Run: `python -m pytest tests/test_scoring.py -v`  
Expected: FAIL because `core.scoring` does not exist.

- [ ] **Step 3: Añadir pytest y la implementación mínima**

En `requirements.txt`, añadir `pytest>=8,<9`. Crear `core/scoring.py`:

```python
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
```

- [ ] **Step 4: Ejecutar la prueba para comprobar que pasa**

Run: `python -m pytest tests/test_scoring.py -v`  
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt core/__init__.py core/scoring.py tests/test_scoring.py
git commit -m "test: add scoring contract"
```

### Task 2: Conectar el contrato a la interfaz y corregir documentación

**Files:**
- Modify: `app/app.py:201-212,446`
- Modify: `README.md:51-60`
- Modify: `schema.sql:59-62`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `core.scoring.score_display` from Task 1.
- Produces: `pill_puntos(puntos, es_exacto)` que representa los cuatro estados del contrato.

- [ ] **Step 1: Extender la prueba para exigir HTML coherente**

```python
from core.scoring import score_display

def test_exact_display_uses_exact_css_class():
    display = score_display(2, True)
    assert display.css_class == "polla-pill--exacto"
    assert "+2" in display.label
```

- [ ] **Step 2: Ejecutar la prueba y confirmar el estado rojo inicial**

Run: `python -m pytest tests/test_scoring.py -v`  
Expected: FAIL until `ScoreDisplay.css_class` is implemented as specified.

- [ ] **Step 3: Usar el módulo desde la app y actualizar copias**

Importar `score_display` en `app/app.py` y reemplazar `pill_puntos` por:

```python
def pill_puntos(puntos, es_exacto=None) -> str:
    display = score_display(puntos, es_exacto)
    return f'<span class="polla-pill {display.css_class}">{display.label}</span>'
```

Cambiar el pie de predicción a: `2 pts por marcador exacto; 1 pt por acertar
G/E/P con marcador distinto; 0 si fallas.` Actualizar README y los comentarios
de `schema.sql` con la misma tabla de tres casos; no alterar el `CASE` SQL que
ya devuelve 2/1/0.

- [ ] **Step 4: Ejecutar verificación local**

Run: `python -m pytest -q; python -c "import ast, pathlib; ast.parse(pathlib.Path('app/app.py').read_text(encoding='utf-8')); print('OK')"`  
Expected: todas las pruebas PASS y `OK`.

- [ ] **Step 5: Commit**

```bash
git add app/app.py README.md schema.sql tests/test_scoring.py core/scoring.py
git commit -m "fix: align exact-score copy with 2 point rule"
```
