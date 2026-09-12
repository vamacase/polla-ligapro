# Plazos de predicción garantizados Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rechazar predicciones tardías en la base de datos aun cuando Task Scheduler o el sync estén retrasados.

**Architecture:** Cada partido tendrá un `cierre_predicciones` calculado desde el orden de su fecha. Un módulo puro calcula cortes y una función RPC de Postgres valida el corte con `now()` antes de insertar/actualizar; `cerrado` queda para presentación y automatización.

**Tech Stack:** Python, pytest, Supabase/Postgres RPC, Streamlit.

**Spec:** `docs/superpowers/specs/2026-09-11-estabilizacion-polla-ligapro-design.md`

## Global Constraints

- Partido 1 y 2 cierran en su kickoff; partido 3+ cierra en kickoff del partido 2.
- La base, no el reloj del navegador ni Task Scheduler, decide el guardado final.
- Un refresco de SofaScore debe recalcular todos los cortes de la fecha.
- No cambiar marcadores, predicciones históricas ni regla de revelación.

---

### Task 1: Fijar el cálculo de cortes con pruebas puras

**Files:**
- Create: `core/deadlines.py`
- Create: `tests/test_deadlines.py`

**Interfaces:**
- Produces: `DeadlineMatch(id: int, kickoff: datetime)`.
- Produces: `calculate_deadlines(matches: list[DeadlineMatch]) -> dict[int, datetime]`.

- [ ] **Step 1: Escribir pruebas de orden y empate de horario**

```python
from datetime import datetime, timezone
from core.deadlines import DeadlineMatch, calculate_deadlines

UTC = timezone.utc

def test_first_two_keep_own_kickoff_and_rest_use_second():
    matches = [
        DeadlineMatch(3, datetime(2026, 9, 13, 0, 0, tzinfo=UTC)),
        DeadlineMatch(1, datetime(2026, 9, 12, 19, 0, tzinfo=UTC)),
        DeadlineMatch(2, datetime(2026, 9, 12, 21, 30, tzinfo=UTC)),
        DeadlineMatch(4, datetime(2026, 9, 13, 18, 0, tzinfo=UTC)),
    ]
    deadlines = calculate_deadlines(matches)
    assert deadlines[1] == matches[1].kickoff
    assert deadlines[2] == matches[2].kickoff
    assert deadlines[3] == matches[2].kickoff
    assert deadlines[4] == matches[2].kickoff

def test_one_match_uses_its_own_kickoff():
    only = DeadlineMatch(1, datetime(2026, 9, 12, 19, 0, tzinfo=UTC))
    assert calculate_deadlines([only]) == {1: only.kickoff}
```

- [ ] **Step 2: Ejecutar para comprobar fallo**

Run: `python -m pytest tests/test_deadlines.py -v`  
Expected: FAIL because `core.deadlines` does not exist.

- [ ] **Step 3: Implementar cálculo determinista**

Crear dataclass inmutable y ordenar por `(kickoff, id)` para que dos partidos a
la misma hora tengan resultado estable. Para cero partidos devolver `{}`; para
uno, usar su kickoff; para dos o más, devolver kickoff propio para índices 0 y
1 y kickoff del índice 1 para los restantes.

- [ ] **Step 4: Ejecutar pruebas**

Run: `python -m pytest tests/test_deadlines.py -v`  
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add core/deadlines.py tests/test_deadlines.py
git commit -m "feat: define prediction deadline policy"
```

### Task 2: Añadir columna, backfill y RPC atómica

**Files:**
- Create: `migrations/003_prediction_deadlines.sql`
- Modify: `schema.sql`
- Test: `tests/test_deadlines.py`

**Interfaces:**
- Produces: `partidos.cierre_predicciones timestamptz`.
- Produces: RPC `guardar_prediccion_segura(p_jugador_id integer, p_partido_id integer, p_gl_pred integer, p_gv_pred integer) returns predicciones`.

- [ ] **Step 1: Escribir casos SQL de aceptación**

```sql
-- Antes del corte debe insertar o actualizar una predicción.
select * from guardar_prediccion_segura(1, 1, 2, 1);
-- Con cierre_predicciones <= now() debe lanzar P0001 con "plazo cerrado".
```

- [ ] **Step 2: Crear migración aditiva**

La migración añadirá `cierre_predicciones` nullable, hará backfill por
`fecha_ronda` con `row_number() over (partition by fecha_ronda order by kickoff,id)`,
marcará la columna `not null` y creará la RPC. La RPC debe: bloquear fila de
partido con `for update`; rechazar si `cierre_predicciones <= now()`;
rechazar goles fuera de 0..15; y ejecutar `insert ... on conflict
(jugador_id,partido_id) do update` con `actualizado_en = now()`.

- [ ] **Step 3: Ejecutar en desarrollo con una copia de datos**

Run: aplicar `migrations/003_prediction_deadlines.sql` en desarrollo y consultar:

```sql
select fecha_ronda, local, visita, kickoff, cierre_predicciones
from partidos order by fecha_ronda, kickoff, id;
```

Expected: en cada fecha, partidos tercero y posteriores comparten exactamente
el corte del segundo partido.

- [ ] **Step 4: Ejecutar pruebas unitarias y SQL de aceptación**

Run: `python -m pytest tests/test_deadlines.py -v`  
Expected: PASS.  
Run: ejecutar ambos casos SQL con un partido de desarrollo abierto y otro
cerrado.  
Expected: el primero guarda; el segundo devuelve `plazo cerrado`.

- [ ] **Step 5: Commit**

```bash
git add migrations/003_prediction_deadlines.sql schema.sql tests/test_deadlines.py
git commit -m "feat: enforce prediction deadlines in database"
```

### Task 3: Recalcular cortes durante sync y usar RPC desde la app

**Files:**
- Modify: `sync/sync_polla.py:61-85,414-490,677-714`
- Modify: `app/app.py:371-512,878-918`
- Create: `services/predictions.py`
- Create: `tests/test_predictions.py`

**Interfaces:**
- Consumes: `calculate_deadlines` y RPC de Task 2.
- Produces: `refresh_round_deadlines(db, round_number) -> int`.
- Produces: `save_prediction(db, player_id, match_id, local_goals, away_goals) -> dict`.

- [ ] **Step 1: Escribir prueba de servicio con cliente falso**

```python
from services.predictions import save_prediction

class FakeClient:
    def rpc(self, name, payload):
        assert name == "guardar_prediccion_segura"
        assert payload["p_gl_pred"] == 2
        return self
    def execute(self):
        return type("Result", (), {"data": [{"id": 99}]})()

def test_save_prediction_uses_atomic_rpc():
    assert save_prediction(FakeClient(), 1, 8, 2, 0)["id"] == 99
```

- [ ] **Step 2: Ejecutar para confirmar fallo**

Run: `python -m pytest tests/test_predictions.py -v`  
Expected: FAIL because `services.predictions` does not exist.

- [ ] **Step 3: Implementar servicio e integración**

`save_prediction` llamará RPC con los cuatro argumentos tipados; no hará
upsert directo. `sync_fixture` y el refresco de kickoff llamarán
`refresh_round_deadlines` después de persistir cada fecha. `vista_predicciones`
capturará el error `plazo cerrado`, lo mostrará como rechazo específico y
recargará la lista. `cargar_partidos_abiertos` filtrará por
`cierre_predicciones > datetime.now(timezone.utc).isoformat()` para interfaz;
la RPC conserva la garantía definitiva. Administración mostrará una columna
`Cierre (Ecuador)`.

- [ ] **Step 4: Verificar regresión**

Run: `python -m pytest -q`  
Expected: PASS.  
Run: `python sync/sync_polla.py fixture <ronda-dev>` y `streamlit run app/app.py`.  
Expected: cortes calculados, partidos 3+ visibles solo hasta el corte del
segundo y guardado tardío rechazado por RPC.

- [ ] **Step 5: Commit**

```bash
git add sync/sync_polla.py app/app.py services/predictions.py tests/test_predictions.py
git commit -m "fix: use database deadline when saving predictions"
```
