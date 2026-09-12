# Diseño: estabilización de Polla Liga Pro

**Fecha:** 2026-09-11  
**Estado:** propuesta aprobada para diseño; pendiente de revisión antes de implementar.

## Objetivo

Convertir la aplicación de una solución funcional para un grupo pequeño en
una aplicación confiable para operar fechas reales, sin cambiar sus reglas de
juego: marcador exacto suma 1 punto por Exacto y 1 por G/E/P (2 en total),
y un acierto de G/E/P no exacto vale 1 punto. Los
partidos 3 en adelante cierran en el kickoff del segundo partido de la fecha.

La estabilización cubre cuatro resultados:

1. Nadie puede suplantar a otro jugador ni leer/modificar la base de datos con
   una credencial pública.
2. La app, los correos y la documentación muestran el mismo reglamento de
   puntaje.
3. Una predicción se rechaza al vencimiento real incluso si la PC de sync se
   atrasa.
4. Los correos se registran, se reintentan y no bloquean el guardado de una
   predicción.

## Decisiones de arquitectura

### 1. Acceso y sesiones

La aplicación seguirá usando PIN por jugador para no imponer cuentas nuevas a
los diez participantes, pero el PIN dejará de ser un dato recuperable.

- `jugadores.pin` se sustituirá por `pin_hash`, generado con `hashlib.scrypt`
  y una sal aleatoria. Se migrarán los PIN existentes una sola vez y se
  eliminará la columna de texto plano después de verificar la migración.
- Se agregará `session_version` por jugador. Al cambiar el PIN se incrementa
  esa versión y se invalidan sus cookies anteriores.
- La cookie contendrá `jugador_id`, vencimiento y `session_version`, protegidos
  con HMAC-SHA256 y un secreto `SESSION_SECRET` de Streamlit. Una cookie
  alterada o vencida no iniciará sesión.
- El PIN administrativo pasará a ser una clave larga guardada exclusivamente
  en secretos. El panel no mostrará PIN ni hash de ningún jugador.
- Se limitarán los intentos fallidos por jugador (cinco en quince minutos),
  con estado persistido en la base. La interfaz mostrará un mensaje neutral
  para no revelar información adicional.

La app y los scripts usarán `SUPABASE_SERVICE_KEY` solo en el servidor. Se
eliminarán las políticas RLS abiertas para `anon`; el acceso de aplicación
quedará restringido a la clave de servicio. Esto es adecuado porque Streamlit
ejecuta las consultas Python en el servidor, no en el navegador.

**Acción requerida al despliegue:** cargar `SUPABASE_SERVICE_KEY`,
`SESSION_SECRET` y un `ADMIN_PASSWORD` fuerte en los secretos de desarrollo,
producción y Streamlit Cloud. Las claves no se escribirán en el repositorio.

### 2. Puntaje como regla única

La fuente de verdad continuará siendo la vista SQL `v_puntos`:

| Caso | Puntos |
|---|---:|
| Marcador exacto | Exacto: 1 + G/E/P: 1 = 2 |
| Resultado G/E/P correcto, marcador distinto | Exacto: 0 + G/E/P: 1 = 1 |
| Incorrecto | Exacto: 0 + G/E/P: 0 = 0 |

Se creará un pequeño módulo puro `core/scoring.py` que define las etiquetas y
la representación de los tres resultados para la interfaz y el correo. La
vista SQL mantiene el cálculo definitivo; el módulo evita que los textos y
las etiquetas vuelvan a divergir. README, pie de predicción, ranking y
`pill_puntos()` se actualizarán en la misma entrega.

### 3. Cierres de predicción

Se añadirá `partidos.cierre_predicciones timestamptz not null`.

Al cargar o refrescar una fecha, el sincronizador calculará el corte según el
orden de kickoff de la fecha:

- partido 1: su propio kickoff;
- partido 2: su propio kickoff;
- partido 3 y posteriores: kickoff del partido 2.

La app solo listará y permitirá guardar predicciones cuyo corte siga en el
futuro. La persistencia se realizará mediante una función SQL RPC que compara
contra `now()` en la base de datos, de modo que un retraso de Task Scheduler
no abre una ventana de edición tardía. `cerrado` se conservará como estado de
presentación y de proceso, pero ya no será la única garantía de plazo.

Cuando SofaScore corrija un horario pendiente, el sync recalculará los cortes
de la fecha. El panel administrativo mostrará kickoff y hora de cierre para
que el cambio sea auditable.

### 4. Cola de notificaciones y observabilidad

Se reemplazará el candado previo al envío por una tabla `notificaciones`:

- `clave` única para deduplicar eventos por tipo, fecha y jugador;
- `estado`: `pendiente`, `enviando`, `enviado` o `fallido`;
- contador de intentos, próximo intento, último error y hora de aceptación
  SMTP;
- `payload jsonb` con el contenido mínimo necesario para reconstruir el correo.

Guardar predicciones solo encola una confirmación; nunca espera a Gmail. El
sync y una tarea ligera ejecutarán un trabajador que toma los pendientes,
envía, confirma el estado únicamente tras aceptación SMTP y aplica reintentos
con espera creciente. Los avisos de fecha terminada, revelación y recordatorios
se encolarán individualmente por destinatario, por lo que el fallo de un correo
no bloquea a los demás.

Se añadirá una tabla de ejecuciones para sync/worker (inicio, fin, resultado,
error, ambiente) y una vista resumida en Administración. Así un fallo de
SofaScore, Gmail o Task Scheduler queda visible sin leer archivos de log.

## Estructura objetivo

La migración será gradual para no alterar la interfaz durante una fecha activa.

```text
app/
  app.py                 # composición Streamlit y navegación
  views/                 # predecir, ranking, resultados, administración
core/
  scoring.py             # etiquetas y reglas puras de presentación
  deadlines.py           # cálculo determinista de cierres
services/
  auth.py                # hash, sesión firmada, bloqueo de intentos
  predictions.py         # llamadas RPC y consultas de predicciones
  notifications.py       # encolado y worker SMTP
repositories/
  polla.py               # acceso Supabase encapsulado
migrations/
  001_security.sql
  002_prediction_deadlines.sql
  003_notifications.sql
tests/
  test_scoring.py
  test_deadlines.py
  test_auth.py
  test_notifications.py
```

`app.py` quedará como punto de entrada, por lo que el despliegue Streamlit no
cambia. El refactor se hará después de extraer funciones sin cambiar su
comportamiento y con pruebas que fijen el resultado actual permitido.

## Migración segura

1. Respaldar las tablas de producción y probar todas las migraciones en la
   base de desarrollo.
2. Añadir columnas y tablas nuevas de forma aditiva; no borrar todavía PIN ni
   políticas existentes.
3. Migrar hashes y verificar que todos los jugadores pueden iniciar sesión en
   desarrollo.
4. Publicar autenticación firmada y RPC de predicción; probar los tres cortes
   de una fecha y la sesión tras refrescar navegador.
5. Cerrar RLS pública y rotar la clave anónima de Supabase si se confirma que
   fue usada fuera del servidor.
6. Activar worker de notificaciones, validar reintento simulado y solo luego
   retirar el flujo anterior.
7. Ejecutar el mismo procedimiento en producción entre fechas, nunca durante
   una ventana de predicción abierta.

Cada migración tendrá una verificación y un camino de reversión documentado.
Los datos de predicciones y resultados existentes no cambian.

## Pruebas y criterios de aceptación

- Puntaje: exacto=1 por Exacto + 1 por G/E/P (total 2), G/E/P no exacto=1,
  fallo=0, incluidos empate y goles iguales.
- Plazos: primera, segunda y tercera posición; ambos lados exactos del corte;
  corrección posterior de kickoff.
- Seguridad: cookie manipulada, cookie vencida, PIN erróneo repetido, cambio
  de PIN que invalida sesión previa y consultas anónimas rechazadas por RLS.
- Notificaciones: SMTP temporalmente caído, reintento posterior, deduplicación
  y una confirmación que no aumenta el tiempo de guardado percibido.
- Regresión: ranking por polla, revelación de predicciones, correos de fecha
  terminada y conversión UTC a Ecuador.

La CI ejecutará estas pruebas y análisis sintáctico sin tocar Supabase ni
SofaScore. Las pruebas de integración se ejecutarán explícitamente contra la
base de desarrollo.

## Despliegue por fases

1. **Corrección visible:** puntaje coherente en app, correos y README, con
   pruebas unitarias.
2. **Identidad y plazos:** migraciones, secretos, sesión firmada, hashes, RLS
   cerrada y RPC de guardado.
3. **Operación recuperable:** cola de correos, worker, historial de ejecuciones
   y panel de salud.
4. **Refactor interno:** extraer módulos y sustituir gradualmente las consultas
   repetidas, manteniendo las pruebas como red de seguridad.

No se agregarán funciones nuevas de producto hasta cerrar las fases 1 a 3.
