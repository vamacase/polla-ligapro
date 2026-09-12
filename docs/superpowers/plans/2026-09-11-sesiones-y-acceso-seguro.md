# Sesiones y acceso seguro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar suplantación por cookie, PINs en texto plano y acceso anónimo abierto a la base.

**Architecture:** El servidor Streamlit firma sesiones HMAC y verifica hashes scrypt. Una migración aditiva prepara columnas y bloqueo de intentos; un script migra PINs una vez; tras validar desarrollo, RLS se cierra y servidor/sync usan únicamente la service key.

**Tech Stack:** Python standard library (`hashlib`, `hmac`, `secrets`), Streamlit cookies, Supabase/Postgres.

**Spec:** `docs/superpowers/specs/2026-09-11-estabilizacion-polla-ligapro-design.md`

## Global Constraints

- Nunca incluir secretos ni PINs reales en código, pruebas, logs o commits.
- Mantener PIN de cuatro dígitos para jugadores; usar `ADMIN_PASSWORD` largo para administrador.
- Ejecutar las migraciones primero en desarrollo y producción solo entre fechas abiertas.
- Streamlit y scripts usan `SUPABASE_SERVICE_KEY`; la clave no se expone al navegador.

---

### Task 1: Construir y probar hash de PIN y token firmado

**Files:**
- Create: `services/__init__.py`
- Create: `services/auth.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Produces: `hash_pin(pin: str) -> str`, `verify_pin(pin: str, encoded: str) -> bool`.
- Produces: `sign_session(player_id: int, version: int, expires_at: int, secret: str) -> str`.
- Produces: `read_session(token: str, secret: str, now: int) -> tuple[int, int] | None`.

- [ ] **Step 1: Escribir pruebas de seguridad puras**

```python
from services.auth import hash_pin, read_session, sign_session, verify_pin

def test_pin_hash_never_contains_the_pin_and_verifies_only_the_right_value():
    encoded = hash_pin("1234")
    assert "1234" not in encoded
    assert verify_pin("1234", encoded)
    assert not verify_pin("9999", encoded)

def test_session_rejects_tampering_and_expiry():
    token = sign_session(7, 3, 2_000, "test-secret")
    assert read_session(token, "test-secret", 1_999) == (7, 3)
    assert read_session(token + "x", "test-secret", 1_999) is None
    assert read_session(token, "test-secret", 2_000) is None
```

- [ ] **Step 2: Ejecutar y confirmar que fallan**

Run: `python -m pytest tests/test_auth.py -v`  
Expected: FAIL because `services.auth` does not exist.

- [ ] **Step 3: Implementar el contrato con librería estándar**

Usar formato `scrypt$16384$8$1$<salt-base64>$<digest-base64>` y
`hmac.compare_digest`. El payload de sesión será JSON compacto
`{"p": player_id, "v": version, "e": expires_at}` codificado en base64 URL;
la firma es `HMAC-SHA256(secret, payload)`. `read_session` exige firma válida y
`expires_at > now`.

- [ ] **Step 4: Ejecutar pruebas**

Run: `python -m pytest tests/test_auth.py -v`  
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add services/__init__.py services/auth.py tests/test_auth.py
git commit -m "feat: add signed sessions and pin hashing"
```

### Task 2: Preparar migración segura y credenciales de servidor

**Files:**
- Create: `migrations/001_security_prepare.sql`
- Create: `scripts/migrate_pin_hashes.py`
- Modify: `db.py:9-24`
- Modify: `.env.example`
- Modify: `.streamlit/secrets.toml.example`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `services.auth.hash_pin`.
- Produces: columnas `pin_hash`, `session_version`, `bloqueado_hasta`, `fallos_pin`; `get_client()` que requiere `SUPABASE_SERVICE_KEY`.

- [ ] **Step 1: Escribir prueba de configuración sin secretos**

```python
import pytest
from db import get_client

def test_client_rejects_missing_service_key(monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="SUPABASE_SERVICE_KEY"):
        get_client()
```

- [ ] **Step 2: Ejecutar la prueba y confirmar que falla**

Run: `python -m pytest tests/test_auth.py::test_client_rejects_missing_service_key -v`  
Expected: FAIL because the current client accepts `SUPABASE_KEY`.

- [ ] **Step 3: Crear migración y script de datos**

La migración añadirá columnas con valores seguros, sin eliminar `pin`:

```sql
alter table jugadores add column if not exists pin_hash text;
alter table jugadores add column if not exists session_version integer not null default 1;
alter table jugadores add column if not exists fallos_pin integer not null default 0;
alter table jugadores add column if not exists bloqueado_hasta timestamptz;
```

El script seleccionará `id,pin`, calculará `hash_pin(str(pin))`, actualizará
solo `pin_hash` y abortará si encuentra un jugador sin PIN. Nunca imprimirá el
valor de PIN. `db.py` elegirá `SUPABASE_SERVICE_KEY` desde entorno o secretos y
fallará explícitamente si falta. Añadir los nombres nuevos, sin valores, a los
dos archivos de ejemplo.

- [ ] **Step 4: Ejecutar pruebas y migración en desarrollo**

Run: `python -m pytest tests/test_auth.py -v`  
Expected: PASS.  
Run: aplicar `migrations/001_security_prepare.sql` en Supabase de desarrollo y luego `python scripts/migrate_pin_hashes.py`.  
Expected: cada jugador recibe hash; el script solo imprime conteos.

- [ ] **Step 5: Commit**

```bash
git add migrations/001_security_prepare.sql scripts/migrate_pin_hashes.py db.py .env.example .streamlit/secrets.toml.example tests/test_auth.py
git commit -m "feat: prepare secure player credentials"
```

### Task 3: Sustituir login, cookie y panel administrativo

**Files:**
- Modify: `app/app.py:23-39,326-369,878-945,950-1035`
- Modify: `admin_jugadores.py`
- Modify: `README.md`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: los cuatro métodos de `services.auth` y columnas de Task 2.
- Produces: `crear_sesion_jugador`, `restaurar_sesion_desde_cookie`, `autenticar_jugador` sin lectura ni muestra de PIN.

- [ ] **Step 1: Añadir pruebas para versión y PIN cambiado**

```python
def test_session_payload_carries_player_and_session_version():
    token = sign_session(9, 4, 9_999, "test-secret")
    assert read_session(token, "test-secret", 100) == (9, 4)
```

- [ ] **Step 2: Ejecutar las pruebas**

Run: `python -m pytest tests/test_auth.py -v`  
Expected: PASS; esta prueba fija el contrato antes de integrar Streamlit.

- [ ] **Step 3: Implementar el flujo integrado**

En login, consultar `id,nombre,pin_hash,session_version,fallos_pin,bloqueado_hasta`;
rechazar bloqueos activos; con éxito verificar hash, resetear fallos, firmar
cookie de 30 días y guardar sesión. Con fallo, incrementar fallos y fijar
`bloqueado_hasta = now + interval '15 minutes'` al quinto intento. Restaurar
sesión solo si token es válido y versión coincide con DB. Al cambiar PIN,
actualizar hash, incrementar `session_version` y emitir una cookie nueva. El
panel lista únicamente nombre y correo. `admin_jugadores.py` crea hash, nunca
un PIN plano.

- [ ] **Step 4: Ejecutar pruebas y prueba manual en desarrollo**

Run: `python -m pytest -q`  
Expected: PASS.  
Run: `streamlit run app/app.py` con secretos de desarrollo.  
Expected: login válido, refresh conserva sesión, cookie alterada devuelve login,
cambio de PIN invalida la cookie anterior y panel no muestra PIN.

- [ ] **Step 5: Commit**

```bash
git add app/app.py admin_jugadores.py README.md tests/test_auth.py services/auth.py
git commit -m "feat: secure player login sessions"
```

### Task 4: Cerrar RLS y retirar el PIN plano tras validación

**Files:**
- Create: `migrations/002_security_enforce.sql`
- Modify: `schema.sql`
- Modify: `README.md`

**Interfaces:**
- Consumes: aplicación desplegada con `SUPABASE_SERVICE_KEY` y todos los `pin_hash` presentes.
- Produces: tablas sin políticas `anon` permisivas y columna `pin` eliminada.

- [ ] **Step 1: Definir la comprobación previa en SQL**

```sql
select count(*) as sin_hash from jugadores where pin_hash is null;
```

- [ ] **Step 2: Ejecutar la comprobación en desarrollo**

Run: ejecutar el SQL anterior en Supabase desarrollo.  
Expected: `sin_hash = 0`; si no es cero, no aplicar esta tarea.

- [ ] **Step 3: Crear la migración de enforcement**

La migración debe hacer, en este orden: eliminar políticas `*_all`, revocar
privilegios a `anon` y `authenticated` sobre tablas públicas, verificar
`pin_hash is not null`, eliminar `jugadores.pin`, y añadir `not null` a
`pin_hash`. No cambiar permisos de `service_role`, que usa el servidor.

- [ ] **Step 4: Validar en desarrollo y luego producción entre fechas**

Run: aplicar migración en desarrollo, reiniciar Streamlit local y ejecutar sync
de desarrollo.  
Expected: app y sync funcionan; una llamada REST con anon recibe 401/403.  
Run: tras respaldo y secretos de producción confirmados, repetir en producción
fuera de una ventana de predicción.  
Expected: mismo resultado y cero cambios de predicciones/resultados.

- [ ] **Step 5: Commit**

```bash
git add migrations/002_security_enforce.sql schema.sql README.md
git commit -m "security: restrict database access to server"
```
