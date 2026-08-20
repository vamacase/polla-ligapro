# Polla Liga Pro Ecuador

Webapp para que 10 amigos predigan marcadores de la Liga Pro y compitan en un ranking.

## Arquitectura

- **Base de datos**: Supabase (Postgres gratis, hospedado).
- **Webapp**: Streamlit (`app/app.py`), hospedada en Streamlit Community Cloud.
- **Sync de datos**: `sync/sync_polla.py`, corre en tu PC (necesita Playwright para
  pasar Cloudflare de SofaScore — no puede correr en el hosting gratuito). Reusa
  el scraper de `10-prediction/src/sofascore.py`.

```
11-polla-ligapro/
├── app/app.py            # webapp (login, predicciones, ranking)
├── sync/sync_polla.py    # corre en tu PC: sube fixture y resultados
├── admin_jugadores.py    # alta de jugadores (nombre + PIN)
├── db.py                 # conexión compartida a Supabase
├── schema.sql            # esquema de base de datos
└── requirements.txt
```

## Ambientes: desarrollo vs producción

Hay dos bases de Supabase separadas para no arriesgar los datos reales de la
polla al probar cambios:

| Ambiente | Archivo de credenciales | Quién lo usa |
|---|---|---|
| **Desarrollo** | `.env` | `streamlit run app/app.py` local (por defecto), y `sync_polla.py`/`admin_jugadores.py` sin flags |
| **Producción** | `.env.prod` (local) / Secrets de Streamlit Cloud (deploy) | La app desplegada en `polla-papers-ligapro.streamlit.app`, y los scripts de sync/admin cuando se les pasa `--prod` |

**Regla práctica:** cualquier prueba local (`streamlit run app/app.py`) apunta
siempre a desarrollo — nunca toca los datos reales de los 10 amigos. Para
operar sobre la polla real desde la terminal (cargar el fixture de verdad,
cerrar resultados reales, dar de alta un jugador real) hay que agregar
`--prod` explícitamente:

```bash
python sync_polla.py fixture --prod        # actualiza la POLLA REAL
python sync_polla.py resultados --prod
python admin_jugadores.py agregar "Nombre Apellido" 1234 --prod
```

Sin `--prod`, estos mismos comandos operan sobre la base de desarrollo — sirve
para probar el flujo completo (fixture ficticio, predicciones, resultados)
sin riesgo. El código (`app/app.py`) se despliega a producción con cada
`git push` a `master` (Streamlit Cloud redeploya solo), pero **los datos
nunca se mezclan** porque cada ambiente tiene su propio proyecto Supabase.

## Puntaje

- **1 punto**: aciertas el resultado — marcador exacto (ej. predices 2-1,
  resultado real 2-1) o solo 1X2 (acertar ganador/empate sin el marcador
  exacto) valen lo mismo.
- **0 puntos**: fallas el resultado.

Se sigue distinguiendo el marcador exacto del acierto de solo 1X2 (columna
`es_exacto` en `v_puntos`) para el desempate del ranking y para que la app
marque cuál fue cuál — pero ya no dan puntaje distinto.

## Setup inicial

### 1. Base de datos (Supabase)

1. Crea proyecto en https://supabase.com.
2. En **SQL Editor**, pega y corre `schema.sql`.
3. Copia **Project URL** y **anon public key** desde Settings → API.

### 2. Variables de entorno (local)

```bash
cp .env.example .env
# edita .env con SUPABASE_URL y SUPABASE_KEY
pip install -r requirements.txt
```

### 3. Dar de alta a los jugadores

```bash
python admin_jugadores.py agregar "Juan Perez" 1234
python admin_jugadores.py agregar "Maria Lopez" 5678
# ... uno por cada amigo (10 en total)
python admin_jugadores.py listar
```

### 4. Cargar el primer fixture

```bash
cd sync
python sync_polla.py fixture        # trae los próximos ~10 partidos de SofaScore
```

### 5. Probar la webapp localmente

**Importante:** lanzar desde la **raíz del proyecto** (`11-polla-ligapro/`), no desde
`app/` — el tema de `.streamlit/config.toml` solo se carga si Streamlit arranca con
esa carpeta como directorio de trabajo.

```bash
streamlit run app/app.py
```

## Despliegue en Streamlit Community Cloud

1. Sube este proyecto a un repo de GitHub (puede ser privado).
2. En https://share.streamlit.io → "New app" → selecciona el repo,
   branch, y como **Main file path**: `11-polla-ligapro/app/app.py`.
3. En **Advanced settings → Secrets**, pega el contenido de
   `.streamlit/secrets.toml.example` con tus valores reales de Supabase.
4. Deploy. Comparte el link con tus 10 amigos.

## Flujo de cada fecha (jornada)

Antes de que empiecen los partidos de la fecha:

```bash
cd sync
python sync_polla.py fixture        # sube los próximos partidos
```

Los amigos entran a la webapp y predicen hasta el kickoff de cada partido
(se cierra automáticamente al iniciar).

Después de jugada la fecha:

```bash
python sync_polla.py resultados     # trae marcadores reales, cierra partidos, calcula puntos
```

El ranking se recalcula solo (es una vista SQL sobre las predicciones).

### 7. Sync automático de resultados (GitHub Actions)

`.github/workflows/sync-resultados.yml` corre `sync_polla.py resultados --prod`
cada 3 horas (cron) o manualmente desde la pestaña *Actions* del repo
(*Run workflow*) — así no hace falta correrlo a mano en tu PC. Usa una copia
vendorizada de `sofascore.py` en `sync/_vendor/` (el runner de GitHub no tiene
acceso al monorepo local con `10-prediction/src`) y un navegador virtual
(`xvfb`) porque `SofaScore` abre Chromium en modo visible.

Requiere estos **Secrets** del repo (Settings → Secrets and variables →
Actions), tomados de `.env.prod`:

- `POLLA_SUPABASE_URL`
- `POLLA_SUPABASE_KEY`

Solo cubre resultados (no `fixture`, que sigue corriendo local porque depende
de `predecir.py`, no vendorizado).
