-- Migración: tabla de escudos cacheados (fix de logos rotos por bloqueo
-- Cloudflare de la API de imágenes de SofaScore).
create table if not exists equipos (
    id bigint primary key,
    logo_base64 text,
    actualizado_en timestamptz not null default now()
);

alter table equipos enable row level security;
drop policy if exists equipos_all on equipos;
create policy equipos_all on equipos for all using (true) with check (true);
