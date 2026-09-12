-- Preparación aditiva: aplicar y verificar primero en desarrollo.
-- No elimina jugadores.pin ni modifica políticas RLS.
alter table jugadores add column if not exists pin_hash text;
alter table jugadores add column if not exists session_version integer not null default 1;
alter table jugadores add column if not exists fallos_pin integer not null default 0;
alter table jugadores add column if not exists bloqueado_hasta timestamptz;
-- Permitir altas con solo hash durante la transición, conservando los PIN existentes.
alter table jugadores alter column pin drop not null;
