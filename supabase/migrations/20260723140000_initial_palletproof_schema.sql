begin;

create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;
set local search_path = public, extensions;

create schema if not exists app;

create or replace function app.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organizations_slug_safe check (slug ~ '^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$')
);

create table if not exists public.sites (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  name text not null,
  slug text not null,
  timezone text not null default 'Europe/Copenhagen',
  address text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, slug),
  unique (organization_id, id),
  constraint sites_slug_safe check (slug ~ '^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$')
);

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.memberships (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  site_id uuid references public.sites(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint memberships_role_valid check (role in ('owner', 'admin', 'site_admin', 'viewer')),
  constraint memberships_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred
);

create unique index if not exists memberships_unique_org_user
  on public.memberships (organization_id, user_id)
  where site_id is null;

create unique index if not exists memberships_unique_site_user
  on public.memberships (site_id, user_id)
  where site_id is not null;

create table if not exists public.devices (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  site_id uuid not null references public.sites(id) on delete restrict,
  serial_number text not null unique,
  display_name text not null default '',
  status text not null default 'unprovisioned',
  provisioned_at timestamptz,
  last_heartbeat_at timestamptz,
  software_version text not null default '',
  last_update_id text not null default '',
  update_policy_override text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint devices_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred,
  constraint devices_status_valid check (status in ('unprovisioned', 'online', 'offline', 'recording', 'error', 'disabled')),
  constraint devices_update_policy_valid check (update_policy_override is null or update_policy_override in ('force', 'night')),
  constraint devices_serial_safe check (serial_number ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
);

create table if not exists public.device_activation_tokens (
  id uuid primary key default gen_random_uuid(),
  device_id uuid not null references public.devices(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.device_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  site_id uuid not null references public.sites(id) on delete cascade,
  device_id uuid not null references public.devices(id) on delete cascade,
  event_type text not null,
  severity text not null default 'info',
  message text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint device_events_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred,
  constraint device_events_severity_valid check (severity in ('debug', 'info', 'warning', 'error', 'critical'))
);

create table if not exists public.videos (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete restrict,
  site_id uuid not null references public.sites(id) on delete restrict,
  device_id uuid not null references public.devices(id) on delete restrict,
  order_number text not null,
  filename text not null,
  storage_bucket text not null default 'videos',
  storage_path text not null unique,
  status text not null default 'pending_upload',
  privacy_status text not null default 'not_processed',
  started_at timestamptz,
  ended_at timestamptz,
  duration_seconds numeric(10, 2),
  size_bytes bigint,
  checksum_sha256 text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint videos_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred,
  constraint videos_status_valid check (status in ('pending_upload', 'uploading', 'uploaded', 'failed', 'deleted')),
  constraint videos_privacy_status_valid check (privacy_status in ('not_processed', 'processed', 'failed', 'not_required'))
);

create table if not exists public.video_shares (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  max_views integer,
  view_count integer not null default 0,
  allow_download boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint video_shares_max_views_positive check (max_views is null or max_views > 0),
  constraint video_shares_view_count_valid check (view_count >= 0)
);

create table if not exists public.video_share_access (
  id uuid primary key default gen_random_uuid(),
  share_id uuid not null references public.video_shares(id) on delete cascade,
  ip_hash text not null default '',
  user_agent text not null default '',
  viewed_at timestamptz not null default now()
);

create table if not exists public.software_rollouts (
  id uuid primary key default gen_random_uuid(),
  update_id text not null unique,
  policy text not null,
  target_ref text not null default 'main',
  target_commit text not null default '',
  version text not null default '',
  description text not null default '',
  enabled boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint software_rollouts_policy_valid check (policy in ('force', 'night'))
);

create table if not exists public.audit_log (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete set null,
  actor_user_id uuid references auth.users(id) on delete set null,
  action text not null,
  resource_type text not null,
  resource_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists sites_organization_id_idx on public.sites (organization_id);
create index if not exists memberships_user_id_idx on public.memberships (user_id);
create index if not exists memberships_organization_id_idx on public.memberships (organization_id);
create index if not exists devices_site_status_idx on public.devices (site_id, status);
create index if not exists devices_last_heartbeat_at_idx on public.devices (last_heartbeat_at);
create index if not exists device_events_device_created_idx on public.device_events (device_id, created_at desc);
create index if not exists videos_order_number_idx on public.videos (order_number);
create index if not exists videos_site_created_idx on public.videos (site_id, created_at desc);
create index if not exists videos_device_created_idx on public.videos (device_id, created_at desc);
create index if not exists video_shares_video_id_idx on public.video_shares (video_id);
create index if not exists audit_log_org_created_idx on public.audit_log (organization_id, created_at desc);

drop trigger if exists organizations_set_updated_at on public.organizations;
create trigger organizations_set_updated_at
before update on public.organizations
for each row execute function app.set_updated_at();

drop trigger if exists sites_set_updated_at on public.sites;
create trigger sites_set_updated_at
before update on public.sites
for each row execute function app.set_updated_at();

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function app.set_updated_at();

drop trigger if exists memberships_set_updated_at on public.memberships;
create trigger memberships_set_updated_at
before update on public.memberships
for each row execute function app.set_updated_at();

drop trigger if exists devices_set_updated_at on public.devices;
create trigger devices_set_updated_at
before update on public.devices
for each row execute function app.set_updated_at();

drop trigger if exists videos_set_updated_at on public.videos;
create trigger videos_set_updated_at
before update on public.videos
for each row execute function app.set_updated_at();

drop trigger if exists video_shares_set_updated_at on public.video_shares;
create trigger video_shares_set_updated_at
before update on public.video_shares
for each row execute function app.set_updated_at();

drop trigger if exists software_rollouts_set_updated_at on public.software_rollouts;
create trigger software_rollouts_set_updated_at
before update on public.software_rollouts
for each row execute function app.set_updated_at();

create or replace function app.is_org_member(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select exists (
    select 1
    from public.memberships
    where user_id = auth.uid()
      and organization_id = target_organization_id
  );
$$;

create or replace function app.is_org_admin(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select exists (
    select 1
    from public.memberships
    where user_id = auth.uid()
      and organization_id = target_organization_id
      and role in ('owner', 'admin')
  );
$$;

create or replace function app.can_access_site(target_organization_id uuid, target_site_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select exists (
    select 1
    from public.memberships
    where user_id = auth.uid()
      and organization_id = target_organization_id
      and (site_id is null or site_id = target_site_id)
  );
$$;

create or replace function app.can_access_video(target_video_id uuid)
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
      and app.can_access_site(v.organization_id, v.site_id)
  );
$$;

create or replace function app.can_admin_video(target_video_id uuid)
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
      and app.is_org_admin(v.organization_id)
  );
$$;

revoke all on function app.is_org_member(uuid) from public;
revoke all on function app.is_org_admin(uuid) from public;
revoke all on function app.can_access_site(uuid, uuid) from public;
revoke all on function app.can_access_video(uuid) from public;
revoke all on function app.can_admin_video(uuid) from public;

grant execute on function app.is_org_member(uuid) to authenticated;
grant execute on function app.is_org_admin(uuid) to authenticated;
grant execute on function app.can_access_site(uuid, uuid) to authenticated;
grant execute on function app.can_access_video(uuid) to authenticated;
grant execute on function app.can_admin_video(uuid) to authenticated;

alter table public.organizations enable row level security;
alter table public.sites enable row level security;
alter table public.profiles enable row level security;
alter table public.memberships enable row level security;
alter table public.devices enable row level security;
alter table public.device_activation_tokens enable row level security;
alter table public.device_events enable row level security;
alter table public.videos enable row level security;
alter table public.video_shares enable row level security;
alter table public.video_share_access enable row level security;
alter table public.software_rollouts enable row level security;
alter table public.audit_log enable row level security;

drop policy if exists "Members can read organizations" on public.organizations;
create policy "Members can read organizations"
on public.organizations for select
to authenticated
using (app.is_org_member(id));

drop policy if exists "Owners and admins can update organizations" on public.organizations;
create policy "Owners and admins can update organizations"
on public.organizations for update
to authenticated
using (app.is_org_admin(id))
with check (app.is_org_admin(id));

drop policy if exists "Members can read sites" on public.sites;
create policy "Members can read sites"
on public.sites for select
to authenticated
using (app.can_access_site(organization_id, id));

drop policy if exists "Owners and admins can manage sites" on public.sites;
create policy "Owners and admins can manage sites"
on public.sites for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Users can read own profile" on public.profiles;
create policy "Users can read own profile"
on public.profiles for select
to authenticated
using (id = auth.uid());

drop policy if exists "Users can update own profile" on public.profiles;
create policy "Users can update own profile"
on public.profiles for update
to authenticated
using (id = auth.uid())
with check (id = auth.uid());

drop policy if exists "Members can read memberships in their organizations" on public.memberships;
create policy "Members can read memberships in their organizations"
on public.memberships for select
to authenticated
using (app.is_org_member(organization_id));

drop policy if exists "Owners and admins can manage memberships" on public.memberships;
create policy "Owners and admins can manage memberships"
on public.memberships for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Members can read devices" on public.devices;
create policy "Members can read devices"
on public.devices for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Owners and admins can manage devices" on public.devices;
create policy "Owners and admins can manage devices"
on public.devices for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Owners and admins can read activation tokens" on public.device_activation_tokens;
create policy "Owners and admins can read activation tokens"
on public.device_activation_tokens for select
to authenticated
using (
  exists (
    select 1
    from public.devices d
    where d.id = device_activation_tokens.device_id
      and app.is_org_admin(d.organization_id)
  )
);

drop policy if exists "Members can read device events" on public.device_events;
create policy "Members can read device events"
on public.device_events for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Members can read videos" on public.videos;
create policy "Members can read videos"
on public.videos for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Owners and admins can manage videos" on public.videos;
create policy "Owners and admins can manage videos"
on public.videos for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Members can read video shares" on public.video_shares;
create policy "Members can read video shares"
on public.video_shares for select
to authenticated
using (app.can_access_video(video_id));

drop policy if exists "Owners and admins can manage video shares" on public.video_shares;
create policy "Owners and admins can manage video shares"
on public.video_shares for all
to authenticated
using (app.can_admin_video(video_id))
with check (app.can_admin_video(video_id));

drop policy if exists "Owners and admins can read share access logs" on public.video_share_access;
create policy "Owners and admins can read share access logs"
on public.video_share_access for select
to authenticated
using (
  exists (
    select 1
    from public.video_shares s
    where s.id = video_share_access.share_id
      and app.can_admin_video(s.video_id)
  )
);

drop policy if exists "Members can read software rollouts" on public.software_rollouts;
create policy "Members can read software rollouts"
on public.software_rollouts for select
to authenticated
using (true);

drop policy if exists "Owners and admins can manage software rollouts" on public.software_rollouts;
create policy "Owners and admins can manage software rollouts"
on public.software_rollouts for all
to authenticated
using (
  exists (
    select 1
    from public.memberships
    where user_id = auth.uid()
      and role in ('owner', 'admin')
  )
)
with check (
  exists (
    select 1
    from public.memberships
    where user_id = auth.uid()
      and role in ('owner', 'admin')
  )
);

drop policy if exists "Owners and admins can read audit logs" on public.audit_log;
create policy "Owners and admins can read audit logs"
on public.audit_log for select
to authenticated
using (organization_id is not null and app.is_org_admin(organization_id));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('videos', 'videos', false, 536870912000, array['video/mp4'])
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

comment on table public.organizations is 'PalletProof customers or warehouse partners.';
comment on table public.sites is 'Physical warehouse locations, for example Rhenus Horsens.';
comment on table public.devices is 'Provisioned Raspberry Pi pallet camera units.';
comment on table public.videos is 'Video metadata. MP4 files live in object storage.';
comment on table public.video_shares is 'Revocable customer share links stored as token hashes.';
comment on table public.software_rollouts is 'Backend-managed force/night rollout records.';

commit;
