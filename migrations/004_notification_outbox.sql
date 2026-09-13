-- Cola durable: encolar nunca envía SMTP dentro de una interacción web.
begin;

create table if not exists notificaciones (
    id bigserial primary key,
    clave text not null unique,
    tipo text not null,
    fecha_ronda integer,
    jugador_id integer references jugadores(id) on delete cascade,
    destinatario text not null,
    payload jsonb not null default '{}'::jsonb,
    estado text not null default 'pendiente'
        check (estado in ('pendiente', 'enviando', 'enviado', 'fallido')),
    intentos integer not null default 0,
    proximo_intento timestamptz not null default now(),
    enviando_en timestamptz,
    ultimo_error text,
    aceptado_smtp_en timestamptz,
    creado_en timestamptz not null default now(),
    actualizado_en timestamptz not null default now()
);

create table if not exists ejecuciones_proceso (
    id bigserial primary key,
    proceso text not null,
    iniciado_en timestamptz not null default now(),
    terminado_en timestamptz,
    estado text not null default 'ejecutando',
    detalle text
);

alter table notificaciones enable row level security;
alter table ejecuciones_proceso enable row level security;

create or replace function reclamar_notificaciones(p_limit integer default 25)
returns setof notificaciones
language sql
security definer
set search_path = public
as $$
    with candidatas as (
        select id
        from notificaciones
        where (estado = 'pendiente' and proximo_intento <= now())
           or (estado = 'enviando' and enviando_en < now() - interval '15 minutes')
        order by proximo_intento, id
        limit greatest(p_limit, 1)
        for update skip locked
    )
    update notificaciones as notificacion
    set estado = 'enviando',
        intentos = notificacion.intentos + 1,
        enviando_en = now(),
        actualizado_en = now()
    from candidatas
    where notificacion.id = candidatas.id
    returning notificacion.*;
$$;

revoke all on table notificaciones, ejecuciones_proceso from anon, authenticated;
revoke all on function reclamar_notificaciones(integer) from public, anon, authenticated;

commit;
