-- Cierre irreversible de la transición de credenciales.
-- Aplicar únicamente cuando todos los jugadores tengan pin_hash y tras validar
-- la app con SUPABASE_SERVICE_KEY. service_role conserva su acceso.
begin;

drop policy if exists jugadores_all on jugadores;
drop policy if exists partidos_all on partidos;
drop policy if exists equipos_all on equipos;
drop policy if exists predicciones_all on predicciones;
drop policy if exists notificaciones_enviadas_all on notificaciones_enviadas;

revoke all privileges on table jugadores, partidos, equipos, predicciones,
    notificaciones_enviadas from anon, authenticated;

do $$
begin
    if exists (select 1 from jugadores where pin_hash is null) then
        raise exception 'No se puede retirar jugadores.pin: existen jugadores sin pin_hash';
    end if;
end;
$$;

alter table jugadores drop column if exists pin;
alter table jugadores alter column pin_hash set not null;

commit;
