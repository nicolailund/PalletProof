begin;

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'videos'
      and column_name = 'order_number'
  ) and not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'videos'
      and column_name = 'scanned_id'
  ) then
    alter table public.videos rename column order_number to scanned_id;
  end if;
end;
$$;

drop index if exists public.videos_order_number_idx;
create index if not exists videos_scanned_id_idx on public.videos (scanned_id);

alter table public.videos
  add column if not exists device_serial_number text not null default '',
  add column if not exists device_display_name text not null default '';

update public.videos v
set device_serial_number = coalesce(nullif(v.device_serial_number, ''), d.serial_number),
    device_display_name = coalesce(nullif(v.device_display_name, ''), d.display_name, '')
from public.devices d
where v.device_id = d.id;

alter table public.videos
  alter column device_id drop not null;

alter table public.videos
  drop constraint if exists videos_device_id_fkey;

alter table public.videos
  add constraint videos_device_id_fkey
  foreign key (device_id)
  references public.devices(id)
  on delete set null;

commit;
