# Modularización segura Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reducir `app/app.py` a composición Streamlit sin cambiar comportamiento ya estabilizado.

**Architecture:** Las reglas puras viven en `core`, el acceso a Supabase en repositorios y cada vista recibe un contexto explícito. Se extrae una vista por commit después de que las pruebas de regresión fijen sus consultas y datos visibles.

**Tech Stack:** Python, Streamlit, pytest, Supabase.

**Spec:** `docs/superpowers/specs/2026-09-11-estabilizacion-polla-ligapro-design.md`

## Global Constraints

- Ejecutar solo después de completar los planes de puntaje, acceso, plazos y notificaciones.
- No cambiar tablas, reglas, textos ni navegación mientras se mueve código.
- Cada extracción mantiene `app/app.py` como entrada de Streamlit.
- Cada commit debe pasar `python -m pytest -q` y análisis AST de `app/app.py`.

---

### Task 1: Fijar contratos de consulta y crear contexto de vistas

**Files:**
- Create: `app/views/__init__.py`
- Create: `app/views/context.py`
- Create: `tests/test_view_context.py`
- Modify: `app/app.py:143-200`

**Interfaces:**
- Produces: `ViewContext(db: Client, player_id: int, player_name: str, is_admin: bool)`.
- Produces: `local_time(timestamp) -> pandas.Timestamp` y `team_logo(team_id, size) -> str` como dependencias explícitas de vistas.

- [ ] **Step 1: Escribir prueba de contexto inmutable**

```python
from app.views.context import ViewContext

def test_view_context_carries_only_session_dependencies():
    context = ViewContext(db=object(), player_id=4, player_name="Ana", is_admin=False)
    assert context.player_id == 4
    assert context.is_admin is False
```

- [ ] **Step 2: Ejecutar y comprobar fallo**

Run: `python -m pytest tests/test_view_context.py -v`  
Expected: FAIL because `app.views.context` does not exist.

- [ ] **Step 3: Crear el dataclass y adaptar composición**

Crear `@dataclass(frozen=True) ViewContext`. En `main()`, construirlo una vez
después de restaurar sesión; conservar `db()`, `a_local()` y `logo()` como
adaptadores temporales y pasarlos explícitamente a las vistas extraídas. No
introducir imports de `app.app` dentro de `app/views`.

- [ ] **Step 4: Verificar**

Run: `python -m pytest tests/test_view_context.py -v; python -c "import ast, pathlib; ast.parse(pathlib.Path('app/app.py').read_text(encoding='utf-8')); print('OK')"`  
Expected: PASS y `OK`.

- [ ] **Step 5: Commit**

```bash
git add app/views/__init__.py app/views/context.py tests/test_view_context.py app/app.py
git commit -m "refactor: introduce explicit view context"
```

### Task 2: Extraer vistas de lectura sin modificar su salida

**Files:**
- Create: `app/views/ranking.py`
- Create: `app/views/results.py`
- Create: `tests/test_scoring.py`
- Modify: `app/app.py:587-750`

**Interfaces:**
- Consumes: `ViewContext`, `score_display`, `local_time`, `team_logo`.
- Produces: `render_ranking(context, local_time)` y `render_results(context, local_time, team_logo)`.

- [ ] **Step 1: Añadir prueba de orden de desempate**

```python
def test_ranking_order_prefers_points_then_exact_scores():
    rows = [{"puntos_totales": 4, "aciertos_exactos": 1}, {"puntos_totales": 4, "aciertos_exactos": 2}]
    ordered = sorted(rows, key=lambda row: (-row["puntos_totales"], -row["aciertos_exactos"]))
    assert ordered[0]["aciertos_exactos"] == 2
```

- [ ] **Step 2: Ejecutar la prueba**

Run: `python -m pytest tests/test_scoring.py -v`  
Expected: PASS; esta prueba congela el orden antes de mover la vista.

- [ ] **Step 3: Mover código intacto**

Copiar los cuerpos de `vista_ranking` y `vista_resultados` a los dos módulos,
reemplazando solo lecturas globales por argumentos. En `app.py`, dejar
funciones delegadoras de una línea o llamar directamente desde `main()`. La
tabla, columnas, textos y consultas deben permanecer idénticos.

- [ ] **Step 4: Verificar regresión**

Run: `python -m pytest -q`  
Expected: PASS.  
Run: `streamlit run app/app.py` contra desarrollo y abrir Ranking/Resultados.  
Expected: mismas cinco columnas, desglose por fecha, barras y últimos
resultados que antes de la extracción.

- [ ] **Step 5: Commit**

```bash
git add app/views/ranking.py app/views/results.py app/app.py tests/test_scoring.py
git commit -m "refactor: extract ranking and results views"
```

### Task 3: Extraer vistas mutables y reducir entrada Streamlit

**Files:**
- Create: `app/views/predictions.py`
- Create: `app/views/my_predictions.py`
- Create: `app/views/admin.py`
- Modify: `app/app.py:371-1038`
- Test: `tests/test_auth.py`, `tests/test_predictions.py`, `tests/test_notification_payloads.py`

**Interfaces:**
- Consumes: `ViewContext`, `save_prediction`, `enqueue_confirmation`, autenticación y repositorios ya implementados.
- Produces: `render_predictions(context)`, `render_my_predictions(context)`, `render_admin(context)`.

- [ ] **Step 1: Ejecutar la batería de regresión antes de mover código**

Run: `python -m pytest -q`  
Expected: PASS. Guardar el resultado del comando en la revisión del commit; no
proceder si una prueba existente falla.

- [ ] **Step 2: Extraer una vista por módulo, conservando dependencias explícitas**

Mover cada función de vista completa sin reescribir sus reglas. `render_predictions`
recibe `ViewContext`, consulta mediante `services.predictions` y solo encola
confirmación. `render_admin` nunca selecciona hash, PIN ni payload de email.
`app.py` conservará configuración, CSS, login, sidebar y construcción de tabs.

- [ ] **Step 3: Ejecutar pruebas y flujos manuales de desarrollo**

Run: `python -m pytest -q`  
Expected: PASS.  
Run: `streamlit run app/app.py`.  
Expected: login, cambio de PIN, guardar predicción, sesión renovada, panel admin
y cola de notificaciones operan sin excepciones.

- [ ] **Step 4: Comprobar tamaño y dependencias de entrada**

Run: `(Get-Content app/app.py).Count`  
Expected: menos de 300 líneas, sin consultas directas a `predicciones`,
`partidos` o `notificaciones` dentro de `app.py`.

- [ ] **Step 5: Commit**

```bash
git add app/app.py app/views tests
git commit -m "refactor: separate interactive Streamlit views"
```
