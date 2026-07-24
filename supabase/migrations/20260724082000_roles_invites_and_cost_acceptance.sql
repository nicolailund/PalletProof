begin;

set local search_path = public, extensions;

alter table public.memberships
  drop constraint if exists memberships_role_valid;

alter table public.memberships
  add constraint memberships_role_valid
  check (role in ('owner', 'admin', 'org_admin', 'site_admin', 'viewer', 'site_operator'));

create table if not exists public.billing_acceptances (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  site_id uuid references public.sites(id) on delete set null,
  device_id uuid references public.devices(id) on delete set null,
  accepted_by uuid references auth.users(id) on delete set null,
  acceptance_type text not null,
  terms_version text not null default '2026-07-24',
  summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint billing_acceptances_type_valid
    check (acceptance_type in ('site_created', 'device_created', 'storage_overage'))
);

create index if not exists billing_acceptances_org_created_idx
  on public.billing_acceptances (organization_id, created_at desc);

create index if not exists billing_acceptances_site_created_idx
  on public.billing_acceptances (site_id, created_at desc);

insert into public.platform_admins (user_id)
select id
from auth.users
where lower(email) = 'ndl@sweetspot.me'
on conflict (user_id) do nothing;

create or replace function app.is_org_member(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select app.is_platform_admin()
    or exists (
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
  select app.is_platform_admin()
    or exists (
      select 1
      from public.memberships
      where user_id = auth.uid()
        and organization_id = target_organization_id
        and site_id is null
        and role in ('owner', 'admin', 'org_admin')
    );
$$;

create or replace function app.can_access_site(target_organization_id uuid, target_site_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select app.is_platform_admin()
    or exists (
      select 1
      from public.memberships
      where user_id = auth.uid()
        and organization_id = target_organization_id
        and (site_id is null or site_id = target_site_id)
    );
$$;

create or replace function app.can_manage_site(target_organization_id uuid, target_site_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select app.is_platform_admin()
    or app.is_org_admin(target_organization_id)
    or exists (
      select 1
      from public.memberships
      where user_id = auth.uid()
        and organization_id = target_organization_id
        and site_id = target_site_id
        and role = 'site_admin'
    );
$$;

create or replace function app.is_site_admin(target_organization_id uuid, target_site_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, app
as $$
  select app.is_platform_admin()
    or app.is_org_admin(target_organization_id)
    or exists (
      select 1
      from public.memberships
      where user_id = auth.uid()
        and organization_id = target_organization_id
        and site_id = target_site_id
        and role = 'site_admin'
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
      and app.can_manage_site(v.organization_id, v.site_id)
  );
$$;

create or replace function app.can_manage_video_visibility(target_video_id uuid)
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
      and app.can_manage_site(v.organization_id, v.site_id)
  );
$$;

revoke all on function app.can_manage_site(uuid, uuid) from public;
revoke all on function app.is_site_admin(uuid, uuid) from public;
revoke all on function app.can_manage_video_visibility(uuid) from public;
grant execute on function app.can_manage_site(uuid, uuid) to authenticated;
grant execute on function app.is_site_admin(uuid, uuid) to authenticated;
grant execute on function app.can_manage_video_visibility(uuid) to authenticated;

create or replace function public.current_memberships()
returns table (
  membership_id uuid,
  organization_id uuid,
  organization_name text,
  organization_slug text,
  site_id uuid,
  site_name text,
  site_slug text,
  site_timezone text,
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
    null::uuid as site_id,
    null::text as site_name,
    null::text as site_slug,
    null::text as site_timezone,
    'system_admin'::text as role
  from public.organizations o
  where app.is_platform_admin()

  union all

  select
    m.id as membership_id,
    o.id as organization_id,
    o.name as organization_name,
    o.slug as organization_slug,
    s.id as site_id,
    s.name as site_name,
    s.slug as site_slug,
    s.timezone as site_timezone,
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

drop policy if exists "Members can read organizations" on public.organizations;
create policy "Members can read organizations"
on public.organizations for select
to authenticated
using (app.is_org_member(id));

drop policy if exists "Platform admins can create organizations" on public.organizations;
create policy "Platform admins can create organizations"
on public.organizations for insert
to authenticated
with check (app.is_platform_admin());

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
create policy "Org admins can manage sites"
on public.sites for all
to authenticated
using (app.is_org_admin(organization_id))
with check (app.is_org_admin(organization_id));

drop policy if exists "Members can read memberships in their organizations" on public.memberships;
create policy "Scoped users can read memberships"
on public.memberships for select
to authenticated
using (
  app.is_platform_admin()
  or app.is_org_admin(organization_id)
  or user_id = auth.uid()
  or (site_id is not null and app.is_site_admin(organization_id, site_id))
);

drop policy if exists "Owners and admins can manage memberships" on public.memberships;
create policy "Scoped admins can manage memberships"
on public.memberships for all
to authenticated
using (
  app.is_platform_admin()
  or app.is_org_admin(organization_id)
  or (site_id is not null and role in ('site_admin', 'site_operator') and app.is_site_admin(organization_id, site_id))
)
with check (
  app.is_platform_admin()
  or app.is_org_admin(organization_id)
  or (site_id is not null and role in ('site_admin', 'site_operator') and app.is_site_admin(organization_id, site_id))
);

drop policy if exists "Members can read devices" on public.devices;
create policy "Members can read devices"
on public.devices for select
to authenticated
using (app.can_access_site(organization_id, site_id));

drop policy if exists "Owners and admins can manage devices" on public.devices;
create policy "Scoped admins can manage devices"
on public.devices for all
to authenticated
using (app.can_manage_site(organization_id, site_id))
with check (app.can_manage_site(organization_id, site_id));

drop policy if exists "Owners and admins can read activation tokens" on public.device_activation_tokens;
create policy "Scoped admins can read activation tokens"
on public.device_activation_tokens for select
to authenticated
using (
  exists (
    select 1
    from public.devices d
    where d.id = device_activation_tokens.device_id
      and app.can_manage_site(d.organization_id, d.site_id)
  )
);

drop policy if exists "Admins can create activation tokens" on public.device_activation_tokens;
create policy "Admins can create activation tokens"
on public.device_activation_tokens for insert
to authenticated
with check (
  exists (
    select 1
    from public.devices d
    where d.id = device_activation_tokens.device_id
      and app.can_manage_site(d.organization_id, d.site_id)
  )
);

drop policy if exists "Owners and admins can manage software rollouts" on public.software_rollouts;
create policy "System admins can manage software rollouts"
on public.software_rollouts for all
to authenticated
using (app.is_platform_admin())
with check (app.is_platform_admin());

drop policy if exists "Owners and admins can manage site billing entitlements" on public.site_billing_entitlements;
create policy "Scoped admins can manage site billing entitlements"
on public.site_billing_entitlements for all
to authenticated
using (app.can_manage_site(organization_id, site_id))
with check (app.can_manage_site(organization_id, site_id));

drop policy if exists "Owners and admins can manage device billing" on public.device_billing;
create policy "Scoped admins can manage device billing"
on public.device_billing for all
to authenticated
using (app.can_manage_site(organization_id, site_id))
with check (app.can_manage_site(organization_id, site_id));

alter table public.billing_acceptances enable row level security;

drop policy if exists "Scoped users can read billing acceptances" on public.billing_acceptances;
create policy "Scoped users can read billing acceptances"
on public.billing_acceptances for select
to authenticated
using (
  app.is_platform_admin()
  or app.is_org_admin(organization_id)
  or (site_id is not null and app.can_manage_site(organization_id, site_id))
);

drop policy if exists "Scoped admins can create billing acceptances" on public.billing_acceptances;
create policy "Scoped admins can create billing acceptances"
on public.billing_acceptances for insert
to authenticated
with check (
  accepted_by = auth.uid()
  and (
    app.is_platform_admin()
    or app.is_org_admin(organization_id)
    or (site_id is not null and app.can_manage_site(organization_id, site_id))
  )
);

comment on table public.billing_acceptances is 'Audit log of explicit customer acceptance of site, device and storage overage fees.';
comment on table public.platform_admins is 'PalletProof system administrators. System admins can see and manage all customers, sites, devices and videos.';

commit;
