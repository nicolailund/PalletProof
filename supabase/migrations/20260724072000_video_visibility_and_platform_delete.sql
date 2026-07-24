begin;

set local search_path = public, extensions;

alter table public.videos
  add column if not exists is_hidden boolean not null default false,
  add column if not exists hidden_reason text not null default '',
  add column if not exists hidden_at timestamptz,
  add column if not exists hidden_by uuid references auth.users(id) on delete set null,
  add column if not exists deleted_at timestamptz,
  add column if not exists deleted_by uuid references auth.users(id) on delete set null;

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'videos'
      and column_name = 'deleted_reason'
  ) then
    execute $sql$
      update public.videos
      set deletion_reason = coalesce(nullif(deletion_reason, ''), deleted_reason)
      where deleted_reason <> ''
    $sql$;
    execute 'alter table public.videos drop column deleted_reason';
  end if;
end;
$$;

create index if not exists videos_visibility_idx
  on public.videos (site_id, is_hidden, status, created_at desc);

create or replace function app.can_manage_video_visibility(target_video_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select app.is_platform_admin()
    or exists (
      select 1
      from public.videos v
      join public.memberships m
        on m.organization_id = v.organization_id
       and m.user_id = auth.uid()
      where v.id = target_video_id
        and (
          (m.site_id is null and m.role in ('owner', 'admin'))
          or (m.site_id = v.site_id and m.role in ('owner', 'admin', 'site_admin'))
        )
    );
$$;

create or replace function app.video_can_be_shared(target_video_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select exists (
    select 1
    from public.videos v
    where v.id = target_video_id
      and v.status = 'uploaded'
      and coalesce(v.is_hidden, false) = false
      and v.privacy_status in ('processed', 'not_required')
  );
$$;

revoke all on function app.can_manage_video_visibility(uuid) from public;
revoke all on function app.video_can_be_shared(uuid) from public;
grant execute on function app.can_manage_video_visibility(uuid) to authenticated;
grant execute on function app.video_can_be_shared(uuid) to authenticated;

create or replace function public.hide_video_recording(
  p_video_id uuid,
  p_reason text
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions, app
as $$
declare
  matched_video public.videos%rowtype;
  safe_reason text;
begin
  if auth.uid() is null then
    raise exception 'Authentication required' using errcode = '28000';
  end if;

  safe_reason := trim(coalesce(p_reason, ''));
  if length(safe_reason) < 3 then
    raise exception 'A hide reason is required' using errcode = '22023';
  end if;

  select *
    into matched_video
  from public.videos
  where id = p_video_id
  for update;

  if not found then
    raise exception 'Video not found' using errcode = 'P0002';
  end if;

  if not app.can_manage_video_visibility(p_video_id) then
    raise exception 'Not allowed to hide this video' using errcode = '42501';
  end if;

  if matched_video.status = 'deleted' then
    raise exception 'Deleted videos cannot be hidden' using errcode = '22023';
  end if;

  update public.videos
  set is_hidden = true,
      hidden_reason = safe_reason,
      hidden_at = now(),
      hidden_by = auth.uid()
  where id = p_video_id
  returning * into matched_video;

  update public.video_shares
  set revoked_at = coalesce(revoked_at, now())
  where video_id = p_video_id
    and revoked_at is null;

  insert into public.audit_log (
    organization_id,
    actor_user_id,
    action,
    resource_type,
    resource_id,
    metadata
  )
  values (
    matched_video.organization_id,
    auth.uid(),
    'video_hidden',
    'video',
    matched_video.id,
    jsonb_build_object(
      'site_id', matched_video.site_id,
      'scanned_id', matched_video.scanned_id,
      'filename', matched_video.filename,
      'reason', safe_reason
    )
  );

  return jsonb_build_object(
    'video_id', matched_video.id,
    'is_hidden', matched_video.is_hidden,
    'hidden_reason', matched_video.hidden_reason,
    'hidden_at', matched_video.hidden_at
  );
end;
$$;

create or replace function public.restore_video_recording(
  p_video_id uuid,
  p_reason text
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions, app
as $$
declare
  matched_video public.videos%rowtype;
  safe_reason text;
  previous_reason text;
begin
  if auth.uid() is null then
    raise exception 'Authentication required' using errcode = '28000';
  end if;

  safe_reason := trim(coalesce(p_reason, ''));
  if length(safe_reason) < 3 then
    raise exception 'A restore reason is required' using errcode = '22023';
  end if;

  select *
    into matched_video
  from public.videos
  where id = p_video_id
  for update;

  if not found then
    raise exception 'Video not found' using errcode = 'P0002';
  end if;

  if not app.can_manage_video_visibility(p_video_id) then
    raise exception 'Not allowed to restore this video' using errcode = '42501';
  end if;

  if matched_video.status = 'deleted' then
    raise exception 'Deleted videos cannot be restored' using errcode = '22023';
  end if;

  previous_reason := matched_video.hidden_reason;

  update public.videos
  set is_hidden = false,
      hidden_reason = '',
      hidden_at = null,
      hidden_by = null
  where id = p_video_id
  returning * into matched_video;

  insert into public.audit_log (
    organization_id,
    actor_user_id,
    action,
    resource_type,
    resource_id,
    metadata
  )
  values (
    matched_video.organization_id,
    auth.uid(),
    'video_restored',
    'video',
    matched_video.id,
    jsonb_build_object(
      'site_id', matched_video.site_id,
      'scanned_id', matched_video.scanned_id,
      'filename', matched_video.filename,
      'reason', safe_reason,
      'previous_hidden_reason', previous_reason
    )
  );

  return jsonb_build_object(
    'video_id', matched_video.id,
    'is_hidden', matched_video.is_hidden
  );
end;
$$;

create or replace function public.delete_video_recording(
  p_video_id uuid,
  p_reason text
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions, app
as $$
declare
  matched_video public.videos%rowtype;
  safe_reason text;
begin
  if auth.uid() is null then
    raise exception 'Authentication required' using errcode = '28000';
  end if;

  if not app.is_platform_admin() then
    raise exception 'Only platform admins can delete videos' using errcode = '42501';
  end if;

  safe_reason := trim(coalesce(p_reason, ''));
  if length(safe_reason) < 3 then
    raise exception 'A delete reason is required' using errcode = '22023';
  end if;

  select *
    into matched_video
  from public.videos
  where id = p_video_id
  for update;

  if not found then
    raise exception 'Video not found' using errcode = 'P0002';
  end if;

  update public.videos
  set status = 'deleted',
      is_hidden = true,
      hidden_reason = 'Deleted by platform admin: ' || safe_reason,
      hidden_at = coalesce(hidden_at, now()),
      hidden_by = coalesce(hidden_by, auth.uid()),
      deletion_reason = safe_reason,
      deleted_at = now(),
      deleted_by = auth.uid()
  where id = p_video_id
  returning * into matched_video;

  update public.video_shares
  set revoked_at = coalesce(revoked_at, now())
  where video_id = p_video_id
    and revoked_at is null;

  insert into public.audit_log (
    organization_id,
    actor_user_id,
    action,
    resource_type,
    resource_id,
    metadata
  )
  values (
    matched_video.organization_id,
    auth.uid(),
    'video_deleted',
    'video',
    matched_video.id,
    jsonb_build_object(
      'site_id', matched_video.site_id,
      'scanned_id', matched_video.scanned_id,
      'filename', matched_video.filename,
      'storage_bucket', matched_video.storage_bucket,
      'storage_path', matched_video.storage_path,
      'raw_storage_bucket', coalesce(matched_video.raw_storage_bucket, ''),
      'raw_storage_path', coalesce(matched_video.raw_storage_path, ''),
      'processed_storage_bucket', coalesce(matched_video.processed_storage_bucket, ''),
      'processed_storage_path', coalesce(matched_video.processed_storage_path, ''),
      'reason', safe_reason
    )
  );

  return jsonb_build_object(
    'video_id', matched_video.id,
    'status', matched_video.status,
    'storage_bucket', matched_video.storage_bucket,
    'storage_path', matched_video.storage_path,
    'raw_storage_bucket', coalesce(matched_video.raw_storage_bucket, ''),
    'raw_storage_path', coalesce(matched_video.raw_storage_path, ''),
    'processed_storage_bucket', coalesce(matched_video.processed_storage_bucket, ''),
    'processed_storage_path', coalesce(matched_video.processed_storage_path, '')
  );
end;
$$;

revoke all on function public.hide_video_recording(uuid, text) from public;
revoke all on function public.restore_video_recording(uuid, text) from public;
revoke all on function public.delete_video_recording(uuid, text) from public;
grant execute on function public.hide_video_recording(uuid, text) to authenticated;
grant execute on function public.restore_video_recording(uuid, text) to authenticated;
grant execute on function public.delete_video_recording(uuid, text) to authenticated;

drop policy if exists "Platform admins can read videos" on public.videos;
create policy "Platform admins can read videos"
on public.videos for select
to authenticated
using (app.is_platform_admin());

drop policy if exists "Owners and admins can manage videos" on public.videos;

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
      and (
        app.is_platform_admin()
        or (
          app.can_access_site(v.organization_id, v.site_id)
          and v.status = 'uploaded'
          and coalesce(v.is_hidden, false) = false
          and v.privacy_status in ('processed', 'not_required')
        )
      )
  )
);

drop policy if exists "Owners and admins can delete video objects" on storage.objects;
drop policy if exists "Platform admins can delete video objects" on storage.objects;
create policy "Platform admins can delete video objects"
on storage.objects for delete
to authenticated
using (bucket_id = 'videos' and app.is_platform_admin());

drop policy if exists "Owners and admins can manage video shares" on public.video_shares;
create policy "Owners and admins can manage video shares"
on public.video_shares for all
to authenticated
using (app.can_admin_video(video_id))
with check (app.can_admin_video(video_id) and app.video_can_be_shared(video_id));

comment on column public.videos.is_hidden is 'When true, the metadata remains visible but playback/download/share access is blocked for customer/local users.';
comment on column public.videos.hidden_reason is 'Required human reason for hiding a recording, usually GDPR or operator error.';
comment on column public.videos.deletion_reason is 'Platform-admin reason for deleting the underlying recording from customer-visible use.';

commit;
