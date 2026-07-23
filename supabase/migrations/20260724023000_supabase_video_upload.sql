begin;

set local search_path = public, extensions;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('videos', 'videos', false, 536870912000, array['video/mp4'])
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Devices can upload video objects" on storage.objects;
create policy "Devices can upload video objects"
on storage.objects for insert
to anon, authenticated
with check (
  bucket_id = 'videos'
  and name like 'device-uploads/%'
  and lower(name) like '%.mp4'
);

drop policy if exists "Members can read video objects" on storage.objects;
create policy "Members can read video objects"
on storage.objects for select
to authenticated
using (
  bucket_id = 'videos'
  and exists (
    select 1
    from public.videos v
    where v.storage_bucket = storage.objects.bucket_id
      and v.storage_path = storage.objects.name
      and app.can_access_site(v.organization_id, v.site_id)
  )
);

drop policy if exists "Owners and admins can delete video objects" on storage.objects;
create policy "Owners and admins can delete video objects"
on storage.objects for delete
to authenticated
using (
  bucket_id = 'videos'
  and exists (
    select 1
    from public.videos v
    where v.storage_bucket = storage.objects.bucket_id
      and v.storage_path = storage.objects.name
      and app.is_org_admin(v.organization_id)
  )
);

create or replace function public.register_video_upload(
  p_serial_number text,
  p_activation_token text,
  p_scanned_id text,
  p_filename text,
  p_storage_bucket text,
  p_storage_path text,
  p_size_bytes bigint default null,
  p_started_at timestamptz default null,
  p_ended_at timestamptz default null,
  p_duration_seconds numeric default null,
  p_checksum_sha256 text default '',
  p_metadata jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  matched_device public.devices%rowtype;
  matched_video public.videos%rowtype;
  token_hash_value text;
  safe_metadata jsonb;
  safe_scanned_id text;
  safe_filename text;
  safe_storage_bucket text;
  safe_storage_path text;
  safe_privacy_status text;
begin
  token_hash_value := encode(digest(coalesce(p_activation_token, ''), 'sha256'), 'hex');
  safe_metadata := coalesce(p_metadata, '{}'::jsonb);
  safe_scanned_id := trim(coalesce(p_scanned_id, ''));
  safe_filename := trim(coalesce(p_filename, ''));
  safe_storage_bucket := trim(coalesce(p_storage_bucket, 'videos'));
  safe_storage_path := trim(coalesce(p_storage_path, ''));

  if safe_scanned_id = '' then
    raise exception 'scanned_id is required' using errcode = '22023';
  end if;
  if safe_filename = '' then
    raise exception 'filename is required' using errcode = '22023';
  end if;
  if safe_storage_bucket <> 'videos' then
    raise exception 'storage_bucket must be videos' using errcode = '22023';
  end if;
  if safe_storage_path = '' or safe_storage_path not like 'device-uploads/%' then
    raise exception 'storage_path must be under device-uploads/' using errcode = '22023';
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
    raise exception 'Invalid video upload credentials'
      using errcode = '28000';
  end if;

  safe_privacy_status := case
    when coalesce((safe_metadata->>'privacy_enabled')::boolean, false) then 'processed'
    else 'not_required'
  end;

  insert into public.videos (
    organization_id,
    site_id,
    device_id,
    device_serial_number,
    device_display_name,
    scanned_id,
    filename,
    storage_bucket,
    storage_path,
    status,
    privacy_status,
    started_at,
    ended_at,
    duration_seconds,
    size_bytes,
    checksum_sha256,
    metadata
  )
  values (
    matched_device.organization_id,
    matched_device.site_id,
    matched_device.id,
    matched_device.serial_number,
    coalesce(matched_device.display_name, ''),
    safe_scanned_id,
    safe_filename,
    safe_storage_bucket,
    safe_storage_path,
    'uploaded',
    safe_privacy_status,
    p_started_at,
    p_ended_at,
    p_duration_seconds,
    p_size_bytes,
    trim(coalesce(p_checksum_sha256, '')),
    safe_metadata
  )
  on conflict (storage_path) do update
  set status = 'uploaded',
      privacy_status = excluded.privacy_status,
      device_id = excluded.device_id,
      device_serial_number = excluded.device_serial_number,
      device_display_name = excluded.device_display_name,
      scanned_id = excluded.scanned_id,
      filename = excluded.filename,
      started_at = excluded.started_at,
      ended_at = excluded.ended_at,
      duration_seconds = excluded.duration_seconds,
      size_bytes = excluded.size_bytes,
      checksum_sha256 = excluded.checksum_sha256,
      metadata = public.videos.metadata || excluded.metadata
  returning * into matched_video;

  update public.devices
  set status = 'online',
      last_heartbeat_at = now()
  where id = matched_device.id;

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
    'video_uploaded',
    'info',
    'Video uploaded to Supabase Storage',
    jsonb_build_object(
      'video_id', matched_video.id,
      'scanned_id', matched_video.scanned_id,
      'filename', matched_video.filename,
      'storage_path', matched_video.storage_path
    )
  );

  return jsonb_build_object(
    'video_id', matched_video.id,
    'storage_bucket', matched_video.storage_bucket,
    'storage_path', matched_video.storage_path,
    'status', matched_video.status
  );
end;
$$;

create or replace function public.device_event(
  p_serial_number text,
  p_activation_token text,
  p_event_type text,
  p_severity text default 'info',
  p_message text default '',
  p_metadata jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  matched_device public.devices%rowtype;
  matched_event public.device_events%rowtype;
  token_hash_value text;
  normalized_severity text;
begin
  token_hash_value := encode(digest(coalesce(p_activation_token, ''), 'sha256'), 'hex');
  normalized_severity := coalesce(nullif(trim(p_severity), ''), 'info');

  if normalized_severity not in ('debug', 'info', 'warning', 'error', 'critical') then
    normalized_severity := 'info';
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
    raise exception 'Invalid device event credentials'
      using errcode = '28000';
  end if;

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
    coalesce(nullif(trim(p_event_type), ''), 'device_event'),
    normalized_severity,
    trim(coalesce(p_message, '')),
    coalesce(p_metadata, '{}'::jsonb)
  )
  returning * into matched_event;

  return jsonb_build_object(
    'event_id', matched_event.id,
    'event_type', matched_event.event_type,
    'severity', matched_event.severity
  );
end;
$$;

revoke all on function public.register_video_upload(text, text, text, text, text, text, bigint, timestamptz, timestamptz, numeric, text, jsonb) from public;
revoke all on function public.device_event(text, text, text, text, text, jsonb) from public;

grant execute on function public.register_video_upload(text, text, text, text, text, text, bigint, timestamptz, timestamptz, numeric, text, jsonb) to anon, authenticated;
grant execute on function public.device_event(text, text, text, text, text, jsonb) to anon, authenticated;

commit;
