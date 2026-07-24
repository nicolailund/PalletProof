begin;

set local search_path = public, extensions;

create table if not exists public.platform_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

insert into public.platform_admins (user_id)
values ('7479afb2-85e1-4faf-85bc-9d39328ef465')
on conflict (user_id) do nothing;

create or replace function app.is_platform_admin()
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select exists (
    select 1
    from public.platform_admins
    where user_id = auth.uid()
  );
$$;

revoke all on function app.is_platform_admin() from public;
grant execute on function app.is_platform_admin() to authenticated;

create table if not exists public.billing_price_catalog (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name text not null,
  description text not null default '',
  component text not null,
  billing_period text not null,
  currency text not null default 'DKK',
  unit_amount_minor integer not null default 0,
  unit_label text not null default '',
  included_quantity numeric(12, 2),
  taxable boolean not null default true,
  active boolean not null default true,
  sort_order integer not null default 100,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint billing_price_catalog_component_valid
    check (component in ('hardware_setup', 'site_service', 'device_license', 'storage_addon')),
  constraint billing_price_catalog_period_valid
    check (billing_period in ('one_time', 'monthly')),
  constraint billing_price_catalog_currency_valid
    check (currency ~ '^[A-Z]{3}$'),
  constraint billing_price_catalog_amount_valid
    check (unit_amount_minor >= 0),
  constraint billing_price_catalog_code_safe
    check (code ~ '^[a-z0-9][a-z0-9_.-]{0,63}$')
);

create table if not exists public.organization_billing (
  organization_id uuid primary key references public.organizations(id) on delete cascade,
  billing_email text not null default '',
  billing_name text not null default '',
  vat_number text not null default '',
  stripe_customer_id text unique,
  subscription_status text not null default 'draft',
  currency text not null default 'DKK',
  billing_notes text not null default '',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organization_billing_status_valid
    check (subscription_status in ('draft', 'active', 'trialing', 'past_due', 'paused', 'cancelled')),
  constraint organization_billing_currency_valid
    check (currency ~ '^[A-Z]{3}$')
);

create table if not exists public.site_billing_entitlements (
  site_id uuid primary key references public.sites(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  included_storage_gb numeric(12, 2) not null default 100,
  extra_storage_gb numeric(12, 2) not null default 0,
  retention_days integer not null default 90,
  auto_delete_enabled boolean not null default true,
  protect_shared_videos boolean not null default true,
  warning_threshold_pct integer not null default 80,
  critical_threshold_pct integer not null default 95,
  site_service_price_code text references public.billing_price_catalog(code),
  storage_addon_price_code text references public.billing_price_catalog(code),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint site_billing_entitlements_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred,
  constraint site_billing_entitlements_storage_valid
    check (included_storage_gb >= 0 and extra_storage_gb >= 0),
  constraint site_billing_entitlements_retention_valid
    check (retention_days >= 1),
  constraint site_billing_entitlements_thresholds_valid
    check (
      warning_threshold_pct between 1 and 100
      and critical_threshold_pct between 1 and 100
      and warning_threshold_pct <= critical_threshold_pct
    )
);

create table if not exists public.device_billing (
  device_id uuid primary key references public.devices(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  site_id uuid not null references public.sites(id) on delete cascade,
  billing_status text not null default 'billable',
  hardware_fee_status text not null default 'not_billed',
  hardware_price_code text references public.billing_price_catalog(code),
  license_price_code text references public.billing_price_catalog(code),
  activated_for_billing_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint device_billing_device_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred,
  constraint device_billing_status_valid
    check (billing_status in ('billable', 'included', 'trial', 'paused', 'waived')),
  constraint device_billing_hardware_status_valid
    check (hardware_fee_status in ('not_billed', 'billed', 'waived'))
);

create table if not exists public.billing_usage_snapshots (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  site_id uuid not null references public.sites(id) on delete cascade,
  period_start date not null,
  period_end date not null,
  storage_bytes bigint not null default 0,
  uploaded_video_count integer not null default 0,
  active_device_count integer not null default 0,
  billable_device_count integer not null default 0,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint billing_usage_snapshots_site_belongs_to_org
    foreign key (organization_id, site_id)
    references public.sites (organization_id, id)
    deferrable initially deferred,
  constraint billing_usage_snapshots_period_valid check (period_end >= period_start),
  constraint billing_usage_snapshots_unique_period unique (site_id, period_start, period_end)
);

alter table public.videos
  add column if not exists retention_protected boolean not null default false,
  add column if not exists deleted_at timestamptz,
  add column if not exists deletion_reason text not null default '';

create index if not exists billing_price_catalog_component_idx on public.billing_price_catalog (component, active, sort_order);
create index if not exists organization_billing_status_idx on public.organization_billing (subscription_status);
create index if not exists site_billing_entitlements_org_idx on public.site_billing_entitlements (organization_id);
create index if not exists device_billing_org_site_idx on public.device_billing (organization_id, site_id, billing_status);
create index if not exists billing_usage_snapshots_site_period_idx on public.billing_usage_snapshots (site_id, period_start desc);
create index if not exists videos_retention_cleanup_idx
  on public.videos (site_id, retention_protected, created_at)
  where status = 'uploaded';

drop trigger if exists billing_price_catalog_set_updated_at on public.billing_price_catalog;
create trigger billing_price_catalog_set_updated_at
before update on public.billing_price_catalog
for each row execute function app.set_updated_at();

drop trigger if exists organization_billing_set_updated_at on public.organization_billing;
create trigger organization_billing_set_updated_at
before update on public.organization_billing
for each row execute function app.set_updated_at();

drop trigger if exists site_billing_entitlements_set_updated_at on public.site_billing_entitlements;
create trigger site_billing_entitlements_set_updated_at
before update on public.site_billing_entitlements
for each row execute function app.set_updated_at();

drop trigger if exists device_billing_set_updated_at on public.device_billing;
create trigger device_billing_set_updated_at
before update on public.device_billing
for each row execute function app.set_updated_at();

insert into public.billing_price_catalog (
  code,
  name,
  description,
  component,
  billing_period,
  currency,
  unit_amount_minor,
  unit_label,
  included_quantity,
  sort_order
)
values
  (
    'hardware_setup_unit',
    'Hardware opstart pr. enhed',
    'Engangsbeløb for klargøring, kabinet, montering og levering af én PalletProof-enhed.',
    'hardware_setup',
    'one_time',
    'DKK',
    0,
    'enhed',
    null,
    10
  ),
  (
    'site_service_base',
    'Service fee pr. site',
    'Månedlig platform, support og drift pr. lager/site inkl. basis video-storage.',
    'site_service',
    'monthly',
    'DKK',
    0,
    'site/md',
    100,
    20
  ),
  (
    'device_license_monthly',
    'Softwarelicens pr. enhed',
    'Månedlig licens for aktiv/provisioneret Raspberry Pi-enhed.',
    'device_license',
    'monthly',
    'DKK',
    0,
    'enhed/md',
    null,
    30
  ),
  (
    'storage_extra_gb_monthly',
    'Ekstra video-storage',
    'Månedligt add-on pr. ekstra GB video-storage.',
    'storage_addon',
    'monthly',
    'DKK',
    0,
    'GB/md',
    1,
    40
  )
on conflict (code) do update
set name = excluded.name,
    description = excluded.description,
    component = excluded.component,
    billing_period = excluded.billing_period,
    currency = excluded.currency,
    unit_label = excluded.unit_label,
    included_quantity = excluded.included_quantity,
    sort_order = excluded.sort_order;

insert into public.organization_billing (organization_id)
select id
from public.organizations
on conflict (organization_id) do nothing;

insert into public.site_billing_entitlements (
  organization_id,
  site_id,
  included_storage_gb,
  extra_storage_gb,
  site_service_price_code,
  storage_addon_price_code
)
select
  s.organization_id,
  s.id,
  100,
  0,
  'site_service_base',
  'storage_extra_gb_monthly'
from public.sites s
on conflict (site_id) do nothing;

insert into public.device_billing (
  device_id,
  organization_id,
  site_id,
  hardware_price_code,
  license_price_code,
  activated_for_billing_at
)
select
  d.id,
  d.organization_id,
  d.site_id,
  'hardware_setup_unit',
  'device_license_monthly',
  d.provisioned_at
from public.devices d
on conflict (device_id) do nothing;

drop function if exists public.billing_site_usage(uuid);

create or replace function public.billing_site_usage(p_organization_id uuid default null)
returns table (
  organization_id uuid,
  site_id uuid,
  site_name text,
  included_storage_gb numeric,
  extra_storage_gb numeric,
  total_storage_gb numeric,
  used_storage_bytes bigint,
  used_storage_gb numeric,
  usage_pct numeric,
  uploaded_video_count bigint,
  shared_video_count bigint,
  protected_video_count bigint,
  active_device_count bigint,
  billable_device_count bigint,
  hardware_pending_count bigint,
  auto_delete_enabled boolean,
  protect_shared_videos boolean,
  retention_days integer,
  warning_threshold_pct integer,
  critical_threshold_pct integer
)
language sql
stable
security definer
set search_path = public, app
as $$
  with allowed_sites as (
    select s.*
    from public.sites s
    where (p_organization_id is null or s.organization_id = p_organization_id)
      and app.can_access_site(s.organization_id, s.id)
  ),
  video_usage as (
    select
      v.site_id,
      coalesce(sum(coalesce(v.size_bytes, 0)) filter (where v.status = 'uploaded'), 0)::bigint as used_storage_bytes,
      count(*) filter (where v.status = 'uploaded')::bigint as uploaded_video_count,
      count(*) filter (
        where v.status = 'uploaded'
          and exists (
            select 1
            from public.video_shares vs
            where vs.video_id = v.id
              and vs.revoked_at is null
              and vs.expires_at > now()
          )
      )::bigint as shared_video_count,
      count(*) filter (
        where v.status = 'uploaded'
          and v.retention_protected
      )::bigint as protected_video_count
    from public.videos v
    join allowed_sites s on s.id = v.site_id
    group by v.site_id
  ),
  device_usage as (
    select
      d.site_id,
      count(*) filter (where d.status in ('online', 'recording'))::bigint as active_device_count,
      count(*) filter (
        where d.status <> 'disabled'
          and d.provisioned_at is not null
          and coalesce(db.billing_status, 'billable') = 'billable'
      )::bigint as billable_device_count,
      count(*) filter (
        where d.status <> 'disabled'
          and coalesce(db.hardware_fee_status, 'not_billed') = 'not_billed'
      )::bigint as hardware_pending_count
    from public.devices d
    join allowed_sites s on s.id = d.site_id
    left join public.device_billing db on db.device_id = d.id
    group by d.site_id
  )
  select
    s.organization_id,
    s.id as site_id,
    s.name as site_name,
    coalesce(e.included_storage_gb, 100)::numeric(12, 2) as included_storage_gb,
    coalesce(e.extra_storage_gb, 0)::numeric(12, 2) as extra_storage_gb,
    (coalesce(e.included_storage_gb, 100) + coalesce(e.extra_storage_gb, 0))::numeric(12, 2) as total_storage_gb,
    coalesce(vu.used_storage_bytes, 0)::bigint as used_storage_bytes,
    round((coalesce(vu.used_storage_bytes, 0)::numeric / 1073741824), 2) as used_storage_gb,
    case
      when (coalesce(e.included_storage_gb, 100) + coalesce(e.extra_storage_gb, 0)) <= 0 then 0
      else round(
        (coalesce(vu.used_storage_bytes, 0)::numeric / 1073741824)
        / (coalesce(e.included_storage_gb, 100) + coalesce(e.extra_storage_gb, 0))
        * 100,
        1
      )
    end as usage_pct,
    coalesce(vu.uploaded_video_count, 0)::bigint as uploaded_video_count,
    coalesce(vu.shared_video_count, 0)::bigint as shared_video_count,
    coalesce(vu.protected_video_count, 0)::bigint as protected_video_count,
    coalesce(du.active_device_count, 0)::bigint as active_device_count,
    coalesce(du.billable_device_count, 0)::bigint as billable_device_count,
    coalesce(du.hardware_pending_count, 0)::bigint as hardware_pending_count,
    coalesce(e.auto_delete_enabled, true) as auto_delete_enabled,
    coalesce(e.protect_shared_videos, true) as protect_shared_videos,
    coalesce(e.retention_days, 90) as retention_days,
    coalesce(e.warning_threshold_pct, 80) as warning_threshold_pct,
    coalesce(e.critical_threshold_pct, 95) as critical_threshold_pct
  from allowed_sites s
  left join public.site_billing_entitlements e on e.site_id = s.id
  left join video_usage vu on vu.site_id = s.id
  left join device_usage du on du.site_id = s.id
  order by s.name;
$$;

create or replace function app.ensure_organization_billing()
returns trigger
language plpgsql
security definer
set search_path = public, app
as $$
begin
  insert into public.organization_billing (organization_id)
  values (new.id)
  on conflict (organization_id) do nothing;

  return new;
end;
$$;

create or replace function app.ensure_site_billing_entitlement()
returns trigger
language plpgsql
security definer
set search_path = public, app
as $$
begin
  insert into public.site_billing_entitlements (
    organization_id,
    site_id,
    site_service_price_code,
    storage_addon_price_code
  )
  values (
    new.organization_id,
    new.id,
    'site_service_base',
    'storage_extra_gb_monthly'
  )
  on conflict (site_id) do update
  set organization_id = excluded.organization_id;

  return new;
end;
$$;

create or replace function app.sync_device_billing()
returns trigger
language plpgsql
security definer
set search_path = public, app
as $$
begin
  insert into public.device_billing (
    device_id,
    organization_id,
    site_id,
    hardware_price_code,
    license_price_code,
    activated_for_billing_at
  )
  values (
    new.id,
    new.organization_id,
    new.site_id,
    'hardware_setup_unit',
    'device_license_monthly',
    new.provisioned_at
  )
  on conflict (device_id) do update
  set organization_id = excluded.organization_id,
      site_id = excluded.site_id,
      activated_for_billing_at = coalesce(public.device_billing.activated_for_billing_at, excluded.activated_for_billing_at);

  return new;
end;
$$;

drop trigger if exists organizations_ensure_billing on public.organizations;
create trigger organizations_ensure_billing
after insert on public.organizations
for each row execute function app.ensure_organization_billing();

drop trigger if exists sites_ensure_billing_entitlement on public.sites;
create trigger sites_ensure_billing_entitlement
after insert or update of organization_id on public.sites
for each row execute function app.ensure_site_billing_entitlement();

drop trigger if exists devices_sync_billing on public.devices;
create trigger devices_sync_billing
after insert or update of organization_id, site_id, provisioned_at on public.devices
for each row execute function app.sync_device_billing();

create or replace function public.billing_video_cleanup_candidates(
  p_site_id uuid,
  p_limit integer default 100
)
returns table (
  video_id uuid,
  site_id uuid,
  scanned_id text,
  filename text,
  storage_bucket text,
  storage_path text,
  size_bytes bigint,
  created_at timestamptz,
  has_active_share boolean
)
language sql
stable
security definer
set search_path = public, app
as $$
  select
    v.id as video_id,
    v.site_id,
    v.scanned_id,
    v.filename,
    v.storage_bucket,
    v.storage_path,
    v.size_bytes,
    v.created_at,
    exists (
      select 1
      from public.video_shares vs
      where vs.video_id = v.id
        and vs.revoked_at is null
        and vs.expires_at > now()
    ) as has_active_share
  from public.videos v
  left join public.site_billing_entitlements e on e.site_id = v.site_id
  where v.site_id = p_site_id
    and app.can_access_site(v.organization_id, v.site_id)
    and v.status = 'uploaded'
    and not v.retention_protected
    and (
      coalesce(e.protect_shared_videos, true) = false
      or not exists (
        select 1
        from public.video_shares vs
        where vs.video_id = v.id
          and vs.revoked_at is null
          and vs.expires_at > now()
      )
    )
  order by coalesce(v.ended_at, v.created_at), v.created_at
  limit greatest(1, least(coalesce(p_limit, 100), 500));
$$;

revoke all on function public.billing_site_usage(uuid) from public;
revoke all on function public.billing_video_cleanup_candidates(uuid, integer) from public;
grant execute on function public.billing_site_usage(uuid) to authenticated;
grant execute on function public.billing_video_cleanup_candidates(uuid, integer) to authenticated;

set constraints all immediate;

alter table public.platform_admins enable row level security;
alter table public.billing_price_catalog enable row level security;
alter table public.organization_billing enable row level security;
alter table public.site_billing_entitlements enable row level security;
alter table public.device_billing enable row level security;
alter table public.billing_usage_snapshots enable row level security;

drop policy if exists "Platform admins can read platform admins" on public.platform_admins;
create policy "Platform admins can read platform admins"
on public.platform_admins for select
to authenticated
using (app.is_platform_admin());

drop policy if exists "Members can read active billing prices" on public.billing_price_catalog;
create policy "Members can read active billing prices"
on public.billing_price_catalog for select
to authenticated
using (active);

drop policy if exists "Platform admins can manage billing prices" on public.billing_price_catalog;
create policy "Platform admins can manage billing prices"
on public.billing_price_catalog for all
to authenticated
using (app.is_platform_admin())
with check (app.is_platform_admin());

drop policy if exists "Members can read organization billing" on public.organization_billing;
create policy "Members can read organization billing"
on public.organization_billing for select
to authenticated
using (app.is_org_member(organization_id));

drop policy if exists "Owners and admins can manage organization billing" on public.organization_billing;
create policy "Owners and admins can manage organization billing"
on public.organization_billing for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Members can read site billing entitlements" on public.site_billing_entitlements;
create policy "Members can read site billing entitlements"
on public.site_billing_entitlements for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Owners and admins can manage site billing entitlements" on public.site_billing_entitlements;
create policy "Owners and admins can manage site billing entitlements"
on public.site_billing_entitlements for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Members can read device billing" on public.device_billing;
create policy "Members can read device billing"
on public.device_billing for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Owners and admins can manage device billing" on public.device_billing;
create policy "Owners and admins can manage device billing"
on public.device_billing for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Members can read billing usage snapshots" on public.billing_usage_snapshots;
create policy "Members can read billing usage snapshots"
on public.billing_usage_snapshots for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Owners and admins can manage billing usage snapshots" on public.billing_usage_snapshots;
create policy "Owners and admins can manage billing usage snapshots"
on public.billing_usage_snapshots for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

comment on table public.billing_price_catalog is 'Commercial PalletProof price catalog. Stripe price IDs can be attached later in metadata.';
comment on table public.organization_billing is 'Billing account state per customer organization.';
comment on table public.site_billing_entitlements is 'Storage and retention entitlements per physical warehouse site.';
comment on table public.device_billing is 'Hardware setup fee and monthly license billing state per device.';
comment on table public.billing_usage_snapshots is 'Monthly billing usage snapshots for audit and future Stripe usage ingestion.';
comment on function public.billing_site_usage(uuid) is 'Current storage, video and billable device usage per accessible site.';
comment on function public.billing_video_cleanup_candidates(uuid, integer) is 'Oldest uploaded videos that can be deleted first when a site exceeds storage entitlement.';

commit;
