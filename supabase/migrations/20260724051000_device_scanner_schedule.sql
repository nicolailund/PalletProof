begin;

set local search_path = public, extensions;

alter table public.devices
  add column if not exists scanner_schedule_enabled boolean not null default false,
  add column if not exists scanner_active_start time not null default time '06:00',
  add column if not exists scanner_active_end time not null default time '18:00',
  add column if not exists scanner_active_days smallint[] not null default array[1, 2, 3, 4, 5, 6, 7]::smallint[];

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'devices_scanner_active_days_valid'
      and conrelid = 'public.devices'::regclass
  ) then
    alter table public.devices
      add constraint devices_scanner_active_days_valid
      check (
        array_length(scanner_active_days, 1) between 1 and 7
        and scanner_active_days <@ array[1, 2, 3, 4, 5, 6, 7]::smallint[]
      );
  end if;
end;
$$;

create or replace function app.device_scanner_schedule(target_device_id uuid)
returns jsonb
language sql
stable
security definer
set search_path = public, app
as $$
  select jsonb_build_object(
    'enabled', d.scanner_schedule_enabled,
    'active_start', to_char(d.scanner_active_start, 'HH24:MI'),
    'active_end', to_char(d.scanner_active_end, 'HH24:MI'),
    'active_days', to_jsonb(d.scanner_active_days),
    'timezone', coalesce(nullif(s.timezone, ''), 'Europe/Copenhagen')
  )
  from public.devices d
  join public.sites s on s.id = d.site_id
  where d.id = target_device_id;
$$;

revoke all on function app.device_scanner_schedule(uuid) from public;
grant execute on function app.device_scanner_schedule(uuid) to authenticated;

create or replace function public.activate_device(
  p_serial_number text,
  p_activation_token text,
  p_software_version text default '',
  p_metadata jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  matched_device public.devices%rowtype;
  token_row public.device_activation_tokens%rowtype;
  token_hash_value text;
  safe_metadata jsonb;
  is_first_activation boolean;
begin
  token_hash_value := encode(digest(coalesce(p_activation_token, ''), 'sha256'), 'hex');
  safe_metadata := coalesce(p_metadata, '{}'::jsonb);

  select d.*
    into matched_device
  from public.devices d
  join public.device_activation_tokens t on t.device_id = d.id
  where d.serial_number = trim(coalesce(p_serial_number, ''))
    and t.token_hash = token_hash_value
    and (t.expires_at > now() or t.used_at is not null)
    and d.status <> 'disabled'
  order by t.created_at desc
  limit 1;

  if not found then
    raise exception 'Invalid or expired activation token'
      using errcode = '28000';
  end if;

  select *
    into token_row
  from public.device_activation_tokens
  where device_id = matched_device.id
    and token_hash = token_hash_value
  order by created_at desc
  limit 1;

  is_first_activation := token_row.used_at is null;

  update public.device_activation_tokens
  set used_at = coalesce(used_at, now())
  where id = token_row.id;

  update public.devices
  set status = 'online',
      provisioned_at = coalesce(provisioned_at, now()),
      last_heartbeat_at = now(),
      software_version = coalesce(nullif(trim(p_software_version), ''), software_version),
      metadata = metadata || safe_metadata
  where id = matched_device.id
  returning * into matched_device;

  if is_first_activation then
    insert into public.device_events (
      organization_id,
      site_id,
      device_id,
      event_type,
      severity,
      message,
      metadata
    )
    values (
      matched_device.organization_id,
      matched_device.site_id,
      matched_device.id,
      'device_activated',
      'info',
      'Device activated from provisioning QR',
      safe_metadata
    );
  end if;

  return jsonb_build_object(
    'device_id', matched_device.id,
    'organization_id', matched_device.organization_id,
    'site_id', matched_device.site_id,
    'serial_number', matched_device.serial_number,
    'status', matched_device.status,
    'last_heartbeat_at', matched_device.last_heartbeat_at,
    'scanner_schedule', app.device_scanner_schedule(matched_device.id)
  );
end;
$$;

create or replace function public.device_heartbeat(
  p_serial_number text,
  p_activation_token text,
  p_status text default 'online',
  p_software_version text default '',
  p_last_update_id text default '',
  p_metadata jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  matched_device public.devices%rowtype;
  token_hash_value text;
  normalized_status text;
  safe_metadata jsonb;
begin
  token_hash_value := encode(digest(coalesce(p_activation_token, ''), 'sha256'), 'hex');
  normalized_status := coalesce(nullif(trim(p_status), ''), 'online');
  safe_metadata := coalesce(p_metadata, '{}'::jsonb);

  if normalized_status not in ('online', 'recording', 'error', 'offline') then
    normalized_status := 'online';
  end if;

  select d.*
    into matched_device
  from public.devices d
  join public.device_activation_tokens t on t.device_id = d.id
  where d.serial_number = trim(coalesce(p_serial_number, ''))
    and t.token_hash = token_hash_value
    and t.used_at is not null
    and d.status <> 'disabled'
  order by t.created_at desc
  limit 1;

  if not found then
    raise exception 'Invalid heartbeat credentials'
      using errcode = '28000';
  end if;

  update public.devices
  set status = normalized_status,
      last_heartbeat_at = now(),
      software_version = coalesce(nullif(trim(p_software_version), ''), software_version),
      last_update_id = coalesce(nullif(trim(p_last_update_id), ''), last_update_id),
      metadata = metadata || safe_metadata
  where id = matched_device.id
  returning * into matched_device;

  return jsonb_build_object(
    'device_id', matched_device.id,
    'organization_id', matched_device.organization_id,
    'site_id', matched_device.site_id,
    'serial_number', matched_device.serial_number,
    'status', matched_device.status,
    'last_heartbeat_at', matched_device.last_heartbeat_at,
    'scanner_schedule', app.device_scanner_schedule(matched_device.id)
  );
end;
$$;

revoke all on function public.activate_device(text, text, text, jsonb) from public;
revoke all on function public.device_heartbeat(text, text, text, text, text, jsonb) from public;

grant execute on function public.activate_device(text, text, text, jsonb) to anon, authenticated;
grant execute on function public.device_heartbeat(text, text, text, text, text, jsonb) to anon, authenticated;

comment on column public.devices.scanner_schedule_enabled is 'When true, the device only pulses the hardware scanner trigger during the configured active window.';
comment on column public.devices.scanner_active_start is 'Local site time when scanner trigger activity starts.';
comment on column public.devices.scanner_active_end is 'Local site time when scanner trigger activity ends. If before start, the window crosses midnight.';
comment on column public.devices.scanner_active_days is 'ISO weekdays where the scanner schedule is active: 1=Monday, 7=Sunday.';
comment on function app.device_scanner_schedule(uuid) is 'Cloud payload consumed by PalletProof devices to decide when scanner triggering should be active.';

commit;
