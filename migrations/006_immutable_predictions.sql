-- Todo pronóstico guardado, nuevo o existente, queda definitivo.
-- No modifica ni elimina los marcadores ya registrados.
begin;

create or replace function impedir_modificacion_prediccion()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    raise exception 'prediccion definitiva: no se puede modificar' using errcode = 'P0001';
end;
$$;

drop trigger if exists prediccion_definitiva on predicciones;
create trigger prediccion_definitiva
before update on predicciones
for each row execute function impedir_modificacion_prediccion();

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
    select * into partido from partidos where id = p_partido_id for update;
    if not found then
        raise exception 'partido no encontrado' using errcode = 'P0002';
    end if;
    if partido.cierre_predicciones <= now() then
        raise exception 'plazo cerrado' using errcode = 'P0001';
    end if;
    if p_gl_pred is null or p_gv_pred is null
        or p_gl_pred not between 0 and 15 or p_gv_pred not between 0 and 15 then
        raise exception 'goles fuera de rango' using errcode = 'P0001';
    end if;

    insert into predicciones (jugador_id, partido_id, gl_pred, gv_pred)
    values (p_jugador_id, p_partido_id, p_gl_pred, p_gv_pred)
    on conflict (jugador_id, partido_id) do nothing
    returning * into prediccion;

    if not found then
        raise exception 'prediccion ya guardada: no se puede modificar' using errcode = 'P0001';
    end if;
    return prediccion;
end;
$$;

revoke all on function guardar_prediccion_segura(integer, integer, integer, integer)
    from public, anon, authenticated;
revoke all on function impedir_modificacion_prediccion()
    from public, anon, authenticated;

commit;
