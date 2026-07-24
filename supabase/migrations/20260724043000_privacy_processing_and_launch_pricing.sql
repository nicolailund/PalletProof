begin;

set local search_path = public, extensions;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('videos-raw', 'videos-raw', false, 536870912000, array['video/mp4'])
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

alter table public.videos
  add column if not exists privacy_mode text not null default 'not_required',
  add column if not exists raw_storage_bucket text not null default '',
  add column if not exists raw_storage_path text not null default '',
  add column if not exists processed_storage_bucket text not null default '',
  add column if not exists processed_storage_path text not null default '',
  add column if not exists privacy_processed_at timestamptz,
  add column if not exists privacy_error text not null default '';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'videos_privacy_mode_valid'
      and conrelid = 'public.videos'::regclass
  ) then
    alter table public.videos
      add constraint videos_privacy_mode_valid
      check (privacy_mode in ('not_required', 'local_pi', 'cloud_worker', 'manual'));
  end if;
end;
$$;

create table if not exists public.video_privacy_jobs (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null unique references public.videos(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  site_id uuid not null references public.sites(id) on delete cascade,
  status text not null default 'queued',
  processor text not null default 'cloud_worker',
  priority integer not null default 100,
  attempts integer not null default 0,
  locked_by text not null default '',
  locked_at timestamptz,
  processed_at timestamptz,
  error_message text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint video_privacy_jobs_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred,
  constraint video_privacy_jobs_status_valid
    check (status in ('queued', 'processing', 'processed', 'failed', 'skipped')),
  constraint video_privacy_jobs_processor_valid
    check (processor in ('cloud_worker', 'local_pi', 'manual')),
  constraint video_privacy_jobs_attempts_valid check (attempts >= 0)
);

create index if not exists video_privacy_jobs_queue_idx
  on public.video_privacy_jobs (status, priority, created_at)
  where status in ('queued', 'failed');

create index if not exists video_privacy_jobs_site_status_idx
  on public.video_privacy_jobs (site_id, status, created_at desc);

drop trigger if exists video_privacy_jobs_set_updated_at on public.video_privacy_jobs;
create trigger video_privacy_jobs_set_updated_at
before update on public.video_privacy_jobs
for each row execute function app.set_updated_at();

create or replace function app.normalize_privacy_processor(value text)
returns text
language sql
immutable
as $$
  select case
    when value in ('cloud_worker', 'local_pi', 'manual') then value
    else 'cloud_worker'
  end;
$$;

create or replace function app.sync_video_privacy_job()
returns trigger
language plpgsql
security definer
set search_path = public, app
as $$
declare
  job_processor text;
begin
  job_processor := app.normalize_privacy_processor(coalesce(new.metadata->>'privacy_processor', new.privacy_mode));

  if new.privacy_status = 'not_processed' then
    insert into public.video_privacy_jobs (
      video_id,
      organization_id,
      site_id,
      status,
      processor,
      metadata
    )
    values (
      new.id,
      new.organization_id,
      new.site_id,
      'queued',
      job_processor,
      jsonb_build_object(
        'storage_bucket', new.storage_bucket,
        'storage_path', new.storage_path,
        'privacy_mode', new.privacy_mode
      )
    )
    on conflict (video_id) do update
    set organization_id = excluded.organization_id,
        site_id = excluded.site_id,
        processor = excluded.processor,
        status = case
          when public.video_privacy_jobs.status = 'processed' then public.video_privacy_jobs.status
          else 'queued'
        end,
        error_message = '',
        metadata = public.video_privacy_jobs.metadata || excluded.metadata;
  elsif new.privacy_status = 'processed' then
    update public.video_privacy_jobs
    set status = 'processed',
        processed_at = coalesce(new.privacy_processed_at, now()),
        error_message = ''
    where video_id = new.id;
  elsif new.privacy_status = 'failed' then
    update public.video_privacy_jobs
    set status = 'failed',
        error_message = coalesce(nullif(new.privacy_error, ''), error_message)
    where video_id = new.id;
  end if;

  return new;
end;
$$;

drop trigger if exists videos_sync_privacy_job on public.videos;
create trigger videos_sync_privacy_job
after insert or update of privacy_status, privacy_mode, storage_bucket, storage_path, privacy_error, privacy_processed_at on public.videos
for each row execute function app.sync_video_privacy_job();

drop policy if exists "Devices can upload raw video objects" on storage.objects;
create policy "Devices can upload raw video objects"
on storage.objects for insert
to anon, authenticated
with check (
  bucket_id = 'videos-raw'
  and name like 'raw-uploads/%'
  and lower(name) like '%.mp4'
);

drop policy if exists "Platform admins can read raw video objects" on storage.objects;
create policy "Platform admins can read raw video objects"
on storage.objects for select
to authenticated
using (bucket_id = 'videos-raw' and app.is_platform_admin());

drop policy if exists "Platform admins can delete raw video objects" on storage.objects;
create policy "Platform admins can delete raw video objects"
on storage.objects for delete
to authenticated
using (bucket_id = 'videos-raw' and app.is_platform_admin());

drop function if exists public.register_video_upload(
  text,
  text,
  text,
  text,
  text,
  text,
  bigint,
  timestamptz,
  timestamptz,
  numeric,
  text,
  jsonb
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
  safe_privacy_mode text;
  raw_bucket text;
  raw_path text;
  processed_bucket text;
  processed_path text;
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
  if safe_storage_bucket not in ('videos', 'videos-raw') then
    raise exception 'storage_bucket must be videos or videos-raw' using errcode = '22023';
  end if;
  if safe_storage_bucket = 'videos' and (safe_storage_path = '' or safe_storage_path not like 'device-uploads/%') then
    raise exception 'storage_path must be under device-uploads/' using errcode = '22023';
  end if;
  if safe_storage_bucket = 'videos-raw' and (safe_storage_path = '' or safe_storage_path not like 'raw-uploads/%') then
    raise exception 'raw storage_path must be under raw-uploads/' using errcode = '22023';
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

  safe_privacy_mode := case
    when safe_storage_bucket = 'videos-raw' then 'cloud_worker'
    when safe_metadata->>'privacy_mode' in ('not_required', 'local_pi', 'cloud_worker', 'manual') then safe_metadata->>'privacy_mode'
    when coalesce((safe_metadata->>'privacy_enabled')::boolean, false) then 'local_pi'
    else 'not_required'
  end;

  safe_privacy_status := case
    when safe_metadata->>'privacy_status' in ('not_processed', 'processed', 'failed', 'not_required') then safe_metadata->>'privacy_status'
    when safe_privacy_mode = 'cloud_worker' then 'not_processed'
    when safe_privacy_mode = 'local_pi' then 'processed'
    else 'not_required'
  end;

  raw_bucket := case when safe_privacy_mode = 'cloud_worker' then safe_storage_bucket else '' end;
  raw_path := case when safe_privacy_mode = 'cloud_worker' then safe_storage_path else '' end;
  processed_bucket := case when safe_privacy_status = 'processed' then safe_storage_bucket else '' end;
  processed_path := case when safe_privacy_status = 'processed' then safe_storage_path else '' end;

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
    privacy_mode,
    raw_storage_bucket,
    raw_storage_path,
    processed_storage_bucket,
    processed_storage_path,
    privacy_processed_at,
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
    safe_privacy_mode,
    raw_bucket,
    raw_path,
    processed_bucket,
    processed_path,
    case when safe_privacy_status = 'processed' then now() else null end,
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
      privacy_mode = excluded.privacy_mode,
      raw_storage_bucket = excluded.raw_storage_bucket,
      raw_storage_path = excluded.raw_storage_path,
      processed_storage_bucket = excluded.processed_storage_bucket,
      processed_storage_path = excluded.processed_storage_path,
      privacy_processed_at = excluded.privacy_processed_at,
      privacy_error = '',
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
      'storage_path', matched_video.storage_path,
      'privacy_status', matched_video.privacy_status,
      'privacy_mode', matched_video.privacy_mode
    )
  );

  return jsonb_build_object(
    'video_id', matched_video.id,
    'storage_bucket', matched_video.storage_bucket,
    'storage_path', matched_video.storage_path,
    'status', matched_video.status,
    'privacy_status', matched_video.privacy_status,
    'privacy_mode', matched_video.privacy_mode
  );
end;
$$;

revoke all on function public.register_video_upload(text, text, text, text, text, text, bigint, timestamptz, timestamptz, numeric, text, jsonb) from public;
grant execute on function public.register_video_upload(text, text, text, text, text, text, bigint, timestamptz, timestamptz, numeric, text, jsonb) to anon, authenticated;

alter table public.video_privacy_jobs enable row level security;

drop policy if exists "Members can read video privacy jobs" on public.video_privacy_jobs;
create policy "Members can read video privacy jobs"
on public.video_privacy_jobs for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Admins can manage video privacy jobs" on public.video_privacy_jobs;
create policy "Admins can manage video privacy jobs"
on public.video_privacy_jobs for all
to authenticated
using (app.is_platform_admin() or app.is_org_admin(organization_id))
with check (app.is_platform_admin() or app.is_org_admin(organization_id));

update public.billing_price_catalog
set unit_amount_minor = 499500
where code = 'hardware_setup_unit'
  and unit_amount_minor = 0;

update public.billing_price_catalog
set unit_amount_minor = 149500,
    included_quantity = 250
where code = 'site_service_base'
  and unit_amount_minor = 0;

update public.billing_price_catalog
set unit_amount_minor = 24900
where code = 'device_license_monthly'
  and unit_amount_minor = 0;

update public.billing_price_catalog
set unit_amount_minor = 250
where code = 'storage_extra_gb_monthly'
  and unit_amount_minor = 0;

alter table public.site_billing_entitlements
  alter column included_storage_gb set default 250;

update public.site_billing_entitlements
set included_storage_gb = 250
where included_storage_gb = 100
  and extra_storage_gb = 0;

comment on table public.video_privacy_jobs is 'Queue and audit state for privacy processing such as cloud face blurring before customer-visible playback.';
comment on column public.videos.privacy_mode is 'How this video is expected to satisfy privacy handling: not_required, local_pi, cloud_worker or manual.';
comment on column public.videos.raw_storage_path is 'Path to the restricted raw source object when cloud privacy processing is used.';
comment on column public.videos.processed_storage_path is 'Path to the customer-visible processed object when privacy processing is complete.';

commit;
