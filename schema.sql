-- Esquema Polla Liga Pro Ecuador — Supabase (Postgres)
-- Ejecutar en: Supabase Dashboard -> SQL Editor -> New query -> pegar y correr.

create table if not exists jugadores (
    id serial primary key,
    nombre text unique not null,
    pin text not null  -- 4 dígitos, texto para simplicidad
);

create table if not exists partidos (
    id serial primary key,
    event_id bigint unique not null,   -- id de SofaScore, para evitar duplicados
    fecha_ronda int,                    -- número de fecha/jornada
    kickoff timestamptz not null,       -- fecha y hora del partido
    local text not null,
    visita text not null,
    local_id bigint,                    -- team id de SofaScore (para el logo)
    visita_id bigint,
    gl_real int,                        -- goles local reales (null hasta jugarse)
    gv_real int,                        -- goles visita reales (null hasta jugarse)
    cerrado boolean not null default false  -- true = ya no se puede predecir
);

create table if not exists equipos (
    -- id de SofaScore: team_id para escudos de equipo, o el unique-tournament
    -- id (240) para el logo de la liga. La API de imágenes de SofaScore está
    -- detrás de Cloudflare y bloquea hotlinking directo desde el navegador
    -- (403 aunque se manden Referer/User-Agent); por eso se cachea acá una
    -- sola vez vía Playwright (sync_polla.py sync_logos) en vez de enlazar
    -- en vivo.
    id bigint primary key,
    logo_base64 text,
    actualizado_en timestamptz not null default now()
);

create table if not exists predicciones (
    id serial primary key,
    jugador_id int not null references jugadores(id) on delete cascade,
    partido_id int not null references partidos(id) on delete cascade,
    gl_pred int not null,
    gv_pred int not null,
    creado_en timestamptz not null default now(),
    actualizado_en timestamptz not null default now(),
    unique (jugador_id, partido_id)
);

-- Vista de puntaje por predicción: 3 = marcador exacto, 1 = acierta 1X2, 0 = falla
create or replace view v_puntos as
select
    p.id as prediccion_id,
    p.jugador_id,
    p.partido_id,
    pa.gl_real, pa.gv_real, p.gl_pred, p.gv_pred,
    case
        when pa.gl_real is null or pa.gv_real is null then null
        when p.gl_pred = pa.gl_real and p.gv_pred = pa.gv_real then 3
        when sign(p.gl_pred - p.gv_pred) = sign(pa.gl_real - pa.gv_real) then 1
        else 0
    end as puntos
from predicciones p
join partidos pa on pa.id = p.partido_id;

-- Ranking agregado
create or replace view v_ranking as
select
    j.id as jugador_id,
    j.nombre,
    coalesce(sum(vp.puntos), 0) as puntos_totales,
    count(vp.puntos) filter (where vp.puntos is not null) as partidos_predichos,
    count(vp.puntos) filter (where vp.puntos = 3) as aciertos_exactos
from jugadores j
left join v_puntos vp on vp.jugador_id = j.id
group by j.id, j.nombre
order by puntos_totales desc, aciertos_exactos desc;

-- RLS: la app usa la anon key (no Supabase Auth); el control de acceso real
-- es el PIN validado en la webapp, no RLS. Se habilita RLS con políticas
-- abiertas para que la anon key pueda leer/escribir estas tablas.
alter table jugadores enable row level security;
alter table partidos enable row level security;
alter table equipos enable row level security;
alter table predicciones enable row level security;

drop policy if exists jugadores_all on jugadores;
create policy jugadores_all on jugadores for all using (true) with check (true);

drop policy if exists partidos_all on partidos;
create policy partidos_all on partidos for all using (true) with check (true);

drop policy if exists equipos_all on equipos;
create policy equipos_all on equipos for all using (true) with check (true);

drop policy if exists predicciones_all on predicciones;
create policy predicciones_all on predicciones for all using (true) with check (true);
