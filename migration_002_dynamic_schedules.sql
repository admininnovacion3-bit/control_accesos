-- Ejecuta este archivo si ejecutaste migration_001_schedules.sql ANTES
-- de cambiar a turnos dinámicos. Elimina el turno fijo del perfil y conserva
-- el turno histórico en cada asistencia.

alter table public.attendance
  add column if not exists work_schedule_id bigint references public.work_schedules(id);

alter table public.profiles
  drop column if exists work_schedule_id;

notify pgrst, 'reload schema';
