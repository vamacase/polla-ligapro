# Notificaciones recuperables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enviar correos de forma asíncrona, deduplicada y reintentable sin bloquear al jugador.

**Architecture:** Los flujos de app y sync encolan mensajes con una clave única. Un worker reclama trabajos, usa las plantillas existentes, marca aceptación SMTP solo tras éxito y programa reintentos exponenciales. Un registro de ejecuciones expone fallas en Administración.

**Tech Stack:** Python standard library SMTP, Supabase/Postgres, Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-estabilizacion-polla-ligapro-design.md`

## Global Constraints

- SMTP aceptado no equivale a apertura por destinatario; el estado `enviado` significa aceptación SMTP.
- Un fallo de un destinatario no impide los demás.
- Guardar una predicción nunca llama SMTP directamente.
- Las claves de deduplicación son únicas por evento, fecha y jugador.

---

### Task 1: Crear cola y operaciones atómicas de reclamo

**Files:**
- Create: `migrations/004_notification_outbox.sql`
- Modify: `schema.sql`
- Create: `repositories/__init__.py`
- Create: `repositories/notifications.py`
- Create: `tests/test_notification_repository.py`

**Interfaces:**
- Produces: tabla `notificaciones` y `ejecuciones_proceso`.
- Produces: RPC `reclamar_notificaciones(p_limit integer) returns setof notificaciones`.
- Produces: `enqueue_notification(db, key, kind, round_number, player_id, payload) -> bool`.

- [ ] **Step 1: Escribir prueba de deduplicación con repositorio falso**

```python
from repositories.notifications import notification_key

def test_notification_key_is_stable_per_player_round_and_kind():
    assert notification_key("fecha_terminada", 30, 7) == "fecha_terminada:30:7"
    assert notification_key("fecha_terminada", 30, 7) != notification_key("fecha_terminada", 30, 8)
```

- [ ] **Step 2: Ejecutar para comprobar fallo**

Run: `python -m pytest tests/test_notification_repository.py -v`  
Expected: FAIL because `repositories.notifications` does not exist.

- [ ] **Step 3: Implementar migración y repositorio**

Crear tabla con `clave text unique`, `tipo`, `fecha_ronda`, `jugador_id`,
`destinatario`, `payload jsonb`, `estado`, `intentos`, `proximo_intento`,
`ultimo_error`, `aceptado_smtp_en`, timestamps. La RPC debe reclamar solo
pendientes vencidos o `enviando` estancados más de 15 minutos mediante
`for update skip locked`, cambiar a `enviando` e incrementar intentos. El
repositorio inserta con `on_conflict=clave` y retorna `False` cuando ya existe.

- [ ] **Step 4: Ejecutar pruebas y migración de desarrollo**

Run: `python -m pytest tests/test_notification_repository.py -v`  
Expected: PASS.  
Run: aplicar la migración en Supabase desarrollo y encolar dos veces la misma
clave.  
Expected: una sola fila persistida.

- [ ] **Step 5: Commit**

```bash
git add migrations/004_notification_outbox.sql schema.sql repositories tests/test_notification_repository.py
git commit -m "feat: add durable notification outbox"
```

### Task 2: Extraer envío unitario y crear worker con reintentos

**Files:**
- Modify: `email_notif.py:42-80`
- Create: `services/notification_worker.py`
- Create: `tests/test_notification_worker.py`

**Interfaces:**
- Produces: `send_html(recipient: str, subject: str, html: str) -> bool`.
- Produces: `process_notifications(db, send: Callable[[str, str, str], bool], limit: int = 25) -> dict[str, int]`.

- [ ] **Step 1: Escribir prueba de éxito y reintento**

```python
from services.notification_worker import retry_at
from datetime import datetime, timezone

def test_retry_wait_grows_and_is_bounded():
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert retry_at(now, 1) > now
    assert retry_at(now, 6) <= now.replace(hour=23, minute=59)
```

- [ ] **Step 2: Ejecutar para confirmar fallo**

Run: `python -m pytest tests/test_notification_worker.py -v`  
Expected: FAIL because the worker does not exist.

- [ ] **Step 3: Implementar envío y worker**

Cambiar `_enviar_html` para delegar cada destinatario en `send_html`; conservar
las plantillas. El worker reclama filas, reconstruye asunto/HTML según un
payload explícito (`confirmacion`, `todos_predijeron`, `fecha_terminada`,
`recordatorio_60min`, `recordatorio_faltantes`), marca `enviado` solo si
`send_html` retorna `True` y, si falla, marca `pendiente` con esperas de 5, 15,
60 y 240 minutos, máximo 5 intentos; después marca `fallido` con error seguro.

- [ ] **Step 4: Ejecutar pruebas**

Run: `python -m pytest tests/test_notification_worker.py -v`  
Expected: PASS.  
Run: `python -m pytest -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add email_notif.py services/notification_worker.py tests/test_notification_worker.py
git commit -m "feat: retry failed notification deliveries"
```

### Task 3: Encolar desde app/sync y exponer salud operativa

**Files:**
- Modify: `app/app.py:286-323,486-512,878-945`
- Modify: `sync/sync_polla.py:248-377,515-631,719-747`
- Create: `services/notification_payloads.py`
- Create: `sync/sync_notificaciones_task.bat`
- Modify: `README.md`
- Test: `tests/test_notification_payloads.py`, `tests/test_notification_repository.py`, `tests/test_notification_worker.py`

**Interfaces:**
- Consumes: `enqueue_notification` y `process_notifications`.
- Produces: CLI `python sync/sync_polla.py notificaciones --prod`.
- Produces: `enqueue_confirmation(db, recipient: str, player_name: str, round_number: int, rows: list[dict]) -> bool`.

- [ ] **Step 1: Escribir prueba de que la confirmación solo se encola**

```python
from services.notification_payloads import enqueue_confirmation

def test_confirmation_is_enqueued_with_a_stable_key():
    captured = {}
    def fake_enqueue(db, key, kind, round_number, player_id, payload):
        captured.update(key=key, kind=kind, round_number=round_number, payload=payload)
        return True

    accepted = enqueue_confirmation(
        object(), "ana@example.test", "Ana", 30,
        [{"local": "Manta", "visita": "Aucas", "gl": 2, "gv": 1}],
        enqueue=fake_enqueue,
    )
    assert accepted is True
    assert captured["key"].startswith("confirmacion:30:ana@example.test:")
    assert captured["kind"] == "confirmacion"
    assert captured["payload"]["rows"][0]["gl"] == 2
```

- [ ] **Step 2: Ejecutar y confirmar fallo inicial**

Run: `python -m pytest tests/test_notification_payloads.py -v`  
Expected: FAIL because `services.notification_payloads` does not exist.

- [ ] **Step 3: Integrar encolado y worker**

Crear `enqueue_confirmation` con parámetro inyectable `enqueue` para la prueba
y una clave formada por tipo, fecha, destinatario y un UUID de guardado. Crear
funciones análogas con claves deterministas para revelación, fecha terminada y
recordatorios. App y sync solo llamarán estas funciones. Reemplazar los inserts directos a
`notificaciones_enviadas` por claves de outbox individuales; mantener la tabla
vieja solo hasta comprobar la migración. Añadir modo CLI `notificaciones`,
invocarlo al final de `resultados` y crear el BAT que lo ejecute cada 15
minutos con `--prod`. Registrar inicio, éxito/error y totales en
`ejecuciones_proceso`. El panel Admin mostrará últimos cinco procesos y conteo
de pendientes/fallidos, sin exponer payloads ni secretos.

- [ ] **Step 4: Verificar flujo en desarrollo**

Run: guardar una predicción con SMTP deshabilitado.  
Expected: UI confirma guardado rápido y queda una notificación pendiente.  
Run: habilitar SMTP de desarrollo y ejecutar `python sync/sync_polla.py notificaciones`.  
Expected: fila pasa a `enviado`.  
Run: simular fallo SMTP y repetir.  
Expected: fila queda pendiente con siguiente intento; ningún otro destinatario se bloquea.

- [ ] **Step 5: Commit**

```bash
git add app/app.py sync/sync_polla.py sync/sync_notificaciones_task.bat README.md tests
git commit -m "feat: process notification outbox asynchronously"
```
