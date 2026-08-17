-- Migración: agregar columnas de team_id (SofaScore) para mostrar logos.
alter table partidos add column if not exists local_id bigint;
alter table partidos add column if not exists visita_id bigint;
