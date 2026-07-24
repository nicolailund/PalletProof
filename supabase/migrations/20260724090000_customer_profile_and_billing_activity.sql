begin;

set local search_path = public, extensions;

alter table public.organizations
  add column if not exists legal_name text not null default '',
  add column if not exists contact_name text not null default '',
  add column if not exists contact_email text not null default '',
  add column if not exists contact_phone text not null default '',
  add column if not exists address text not null default '',
  add column if not exists billing_address text not null default '';

update public.organizations
set legal_name = name
where legal_name = '';

create index if not exists organizations_contact_email_idx
  on public.organizations (lower(contact_email))
  where contact_email <> '';

alter table public.sites
  drop constraint if exists sites_address_required;

alter table public.sites
  add constraint sites_address_required
  check (char_length(btrim(address)) > 0)
  not valid;

alter table public.organization_billing
  add column if not exists billing_address text not null default '';

update public.organization_billing ob
set billing_address = o.billing_address
from public.organizations o
where ob.organization_id = o.id
  and ob.billing_address = ''
  and o.billing_address <> '';

create or replace function app.organization_profile_complete(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select exists (
    select 1
    from public.organizations o
    where o.id = target_organization_id
      and btrim(o.name) <> ''
      and btrim(o.contact_name) <> ''
      and btrim(o.contact_email) <> ''
      and btrim(o.contact_phone) <> ''
      and btrim(o.address) <> ''
      and btrim(o.billing_address) <> ''
  );
$$;

revoke all on function app.organization_profile_complete(uuid) from public;
grant execute on function app.organization_profile_complete(uuid) to authenticated;

drop policy if exists "Org admins can manage sites" on public.sites;
create policy "Org admins can manage sites"
on public.sites for all
to authenticated
using (app.is_org_admin(organization_id))
with check (
  app.is_org_admin(organization_id)
  and app.organization_profile_complete(organization_id)
);

create or replace function app.device_billable_in_month(
  p_provisioned_at timestamptz,
  p_period_start date,
  p_period_end date
)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select p_provisioned_at is not null
    and (
      least((p_period_end + 1)::timestamptz, now())
      - greatest(p_provisioned_at, p_period_start::timestamptz)
    ) > interval '5 days';
$$;

revoke all on function app.device_billable_in_month(timestamptz, date, date) from public;
grant execute on function app.device_billable_in_month(timestamptz, date, date) to authenticated;

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
    case when new.provisioned_at is null then null else new.provisioned_at + interval '5 days' end
  )
  on conflict (device_id) do update
  set organization_id = excluded.organization_id,
      site_id = excluded.site_id,
      activated_for_billing_at = case
        when excluded.activated_for_billing_at is null then public.device_billing.activated_for_billing_at
        when public.device_billing.activated_for_billing_at is null then excluded.activated_for_billing_at
        else least(public.device_billing.activated_for_billing_at, excluded.activated_for_billing_at)
      end;

  return new;
end;
$$;

update public.device_billing db
set activated_for_billing_at = d.provisioned_at + interval '5 days'
from public.devices d
where db.device_id = d.id
  and d.provisioned_at is not null
  and (
    db.activated_for_billing_at is null
    or db.activated_for_billing_at = d.provisioned_at
  );

update public.billing_price_catalog
set description = 'Engangsbeløb for klargøring og levering af én PalletProof-enhed.'
where code = 'hardware_setup_unit';

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
  with billing_period as (
    select
      date_trunc('month', now())::date as period_start,
      (date_trunc('month', now()) + interval '1 month - 1 day')::date as period_end
  ),
  allowed_sites as (
    select s.*
    from public.sites s
    where (p_organization_id is null or s.organization_id = p_organization_id)
      and app.can_access_site(s.organization_id, s.id)
  ),
  video_usage as (
    select
      v.site_id,
      coalesce(sum(v.size_bytes) filter (where v.status = 'uploaded'), 0)::bigint as used_storage_bytes,
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
          and app.device_billable_in_month(d.provisioned_at, bp.period_start, bp.period_end)
      )::bigint as billable_device_count,
      count(*) filter (
        where d.status <> 'disabled'
          and coalesce(db.hardware_fee_status, 'not_billed') = 'not_billed'
      )::bigint as hardware_pending_count
    from public.devices d
    join allowed_sites s on s.id = d.site_id
    cross join billing_period bp
    left join public.device_billing db on db.device_id = d.id
    group by d.site_id
  )
  select
    s.organization_id,
    s.id as site_id,
    s.name as site_name,
    coalesce(e.included_storage_gb, 250)::numeric(12, 2) as included_storage_gb,
    coalesce(e.extra_storage_gb, 0)::numeric(12, 2) as extra_storage_gb,
    (coalesce(e.included_storage_gb, 250) + coalesce(e.extra_storage_gb, 0))::numeric(12, 2) as total_storage_gb,
    coalesce(vu.used_storage_bytes, 0)::bigint as used_storage_bytes,
    round((coalesce(vu.used_storage_bytes, 0)::numeric / 1073741824), 2) as used_storage_gb,
    case
      when (coalesce(e.included_storage_gb, 250) + coalesce(e.extra_storage_gb, 0)) <= 0 then 0
      else round(
        (coalesce(vu.used_storage_bytes, 0)::numeric / 1073741824)
        / (coalesce(e.included_storage_gb, 250) + coalesce(e.extra_storage_gb, 0))
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

drop function if exists public.current_memberships();

create function public.current_memberships()
returns table (
  membership_id uuid,
  organization_id uuid,
  organization_name text,
  organization_slug text,
  organization_legal_name text,
  organization_contact_name text,
  organization_contact_email text,
  organization_contact_phone text,
  organization_address text,
  organization_billing_address text,
  site_id uuid,
  site_name text,
  site_slug text,
  site_timezone text,
  site_address text,
  role text
)
language sql
stable
security definer
set search_path = public, app
as $$
  select
    o.id as membership_id,
    o.id as organization_id,
    o.name as organization_name,
    o.slug as organization_slug,
    o.legal_name as organization_legal_name,
    o.contact_name as organization_contact_name,
    o.contact_email as organization_contact_email,
    o.contact_phone as organization_contact_phone,
    o.address as organization_address,
    o.billing_address as organization_billing_address,
    null::uuid as site_id,
    null::text as site_name,
    null::text as site_slug,
    null::text as site_timezone,
    null::text as site_address,
    'system_admin'::text as role
  from public.organizations o
  where app.is_platform_admin()

  union all

  select
    m.id as membership_id,
    o.id as organization_id,
    o.name as organization_name,
    o.slug as organization_slug,
    o.legal_name as organization_legal_name,
    o.contact_name as organization_contact_name,
    o.contact_email as organization_contact_email,
    o.contact_phone as organization_contact_phone,
    o.address as organization_address,
    o.billing_address as organization_billing_address,
    s.id as site_id,
    s.name as site_name,
    s.slug as site_slug,
    s.timezone as site_timezone,
    s.address as site_address,
    m.role
  from public.memberships m
  join public.organizations o on o.id = m.organization_id
  left join public.sites s on s.id = m.site_id
  where m.user_id = auth.uid()
    and not app.is_platform_admin()
  order by organization_name, site_name nulls first, role;
$$;

revoke all on function public.current_memberships() from public;
grant execute on function public.current_memberships() to authenticated;

comment on column public.organizations.legal_name is 'Legal customer name for supplier and billing records.';
comment on column public.organizations.contact_name is 'Primary customer contact name.';
comment on column public.organizations.contact_email is 'Primary customer contact email.';
comment on column public.organizations.contact_phone is 'Primary customer contact phone number.';
comment on column public.organizations.address is 'Customer main address.';
comment on column public.organizations.billing_address is 'Customer invoice address.';
comment on constraint sites_address_required on public.sites is 'New and updated sites must have a physical warehouse address.';
comment on function app.device_billable_in_month(timestamptz, date, date) is 'A device is billable in a calendar month after more than five provisioned days in that month.';
comment on column public.device_billing.activated_for_billing_at is 'First timestamp where the device license can be billed; provisioned_at plus the five day grace period.';
comment on function public.billing_site_usage(uuid) is 'Current storage and monthly billable site/device usage per accessible site. A site is billable when billable_device_count is greater than zero.';

commit;
