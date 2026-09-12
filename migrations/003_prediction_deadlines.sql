-- Garantiza el plazo de predicción en Postgres, no en el navegador ni en el sync.
begin;

alter table partidos add column if not exists cierre_predicciones timestamptz;

with ordenados as (
    select
        id,
        kickoff,
        row_number() over (partition by fecha_ronda order by kickoff, id) as posicion,
        nth_value(kickoff, 2) over (
            partition by fecha_ronda
            order by kickoff, id
            rows between unbounded preceding and unbounded following
        ) as segundo_kickoff
    from partidos
)
update partidos as partido
set cierre_predicciones = case
    when ordenados.posicion <= 2 or ordenados.segundo_kickoff is null
        then ordenados.kickoff
    else ordenados.segundo_kickoff
end
from ordenados
where partido.id = ordenados.id;

alter table partidos alter column cierre_predicciones set not null;

create or replace function guardar_prediccion_segura(
    p_jugador_id integer,
    p_partido_id integer,
    p_gl_pred integer,
    p_gv_pred integer
)
returns predicciones
language plpgsql
security definer
set search_path = public
as $$
declare
    partido partidos%rowtype;
    prediccion predicciones%rowtype;
begin
    select * into partido
    from partidos
    where id = p_partido_id
    for update;

    if not found then
        raise exception 'partido no encontrado' using errcode = 'P0002';
    end if;

    if partido.cierre_predicciones <= now() then
        raise exception 'plazo cerrado' using errcode = 'P0001';
    end if;

    if p_gl_pred not between 0 and 15 or p_gv_pred not between 0 and 15 then
        raise exception 'goles fuera de rango' using errcode = 'P0001';
    end if;

    insert into predicciones (jugador_id, partido_id, gl_pred, gv_pred)
    values (p_jugador_id, p_partido_id, p_gl_pred, p_gv_pred)
    on conflict (jugador_id, partido_id) do update
    set gl_pred = excluded.gl_pred,
        gv_pred = excluded.gv_pred,
        actualizado_en = now()
    returning * into prediccion;

    return prediccion;
end;
$$;

revoke all on function guardar_prediccion_segura(integer, integer, integer, integer)
    from public, anon, authenticated;

commit;
