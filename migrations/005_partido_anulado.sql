-- Permite excluir un partido del cálculo de una fecha sin borrar la fila ni
-- sus predicciones (ej. reprogramación sin fecha definida) -- ver README,
-- sección "Partidos duplicados por reprogramación", y el caso real: Fecha 31,
-- Barcelona SC vs Independiente del Valle, reprogramado sin fecha conocida.
begin;

alter table partidos add column if not exists anulado boolean not null default false;
comment on column partidos.anulado is
    'true = partido excluido del cálculo de su fecha (reprogramado sin fecha '
    'conocida, suspendido, etc.). No otorga puntos aunque se le cargue '
    'gl_real/gv_real, y no cuenta para considerar la fecha "completa". La '
    'fila y las predicciones existentes se conservan, nunca se borran.';

create or replace view v_puntos as
select
    p.id as prediccion_id,
    p.jugador_id,
    p.partido_id,
    pa.gl_real, pa.gv_real, p.gl_pred, p.gv_pred,
    case
        when pa.anulado then null
        when pa.gl_real is null or pa.gv_real is null then null
        when p.gl_pred = pa.gl_real and p.gv_pred = pa.gv_real then 2
        when sign(p.gl_pred - p.gv_pred) = sign(pa.gl_real - pa.gv_real) then 1
        else 0
    end as puntos,
    case
        when pa.anulado then null
        when pa.gl_real is null or pa.gv_real is null then null
        else (p.gl_pred = pa.gl_real and p.gv_pred = pa.gv_real)
    end as es_exacto
from predicciones p
join partidos pa on pa.id = p.partido_id;

commit;
