begin;

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
  order by o.name, s.name nulls first, m.role;
$$;

revoke all on function public.current_memberships() from public;
grant execute on function public.current_memberships() to authenticated;

commit;
