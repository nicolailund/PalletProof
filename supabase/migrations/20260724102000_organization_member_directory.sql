begin;

create or replace function public.organization_members(p_organization_id uuid default null)
returns table (
  membership_id uuid,
  organization_id uuid,
  site_id uuid,
  site_name text,
  user_id uuid,
  email text,
  full_name text,
  role text,
  invited_at timestamptz,
  confirmation_sent_at timestamptz,
  confirmed_at timestamptz,
  last_sign_in_at timestamptz,
  created_at timestamptz
)
language sql
stable
security definer
set search_path = public, app
as $$
  select
    m.id as membership_id,
    m.organization_id,
    m.site_id,
    s.name as site_name,
    m.user_id,
    lower(coalesce(u.email, '')) as email,
    coalesce(nullif(p.full_name, ''), nullif(u.raw_user_meta_data ->> 'full_name', ''), '') as full_name,
    m.role,
    u.invited_at,
    u.confirmation_sent_at,
    u.confirmed_at,
    u.last_sign_in_at,
    m.created_at
  from public.memberships m
  join auth.users u on u.id = m.user_id
  left join public.profiles p on p.id = m.user_id
  left join public.sites s on s.id = m.site_id
  where (p_organization_id is null or m.organization_id = p_organization_id)
    and (
      app.is_platform_admin()
      or app.is_org_admin(m.organization_id)
      or (m.site_id is not null and app.is_site_admin(m.organization_id, m.site_id))
      or m.user_id = auth.uid()
    )
  order by
    s.name nulls first,
    case m.role
      when 'owner' then 1
      when 'admin' then 2
      when 'org_admin' then 3
      when 'site_admin' then 4
      when 'site_operator' then 5
      when 'viewer' then 6
      else 9
    end,
    lower(coalesce(u.email, ''));
$$;

revoke all on function public.organization_members(uuid) from public;
grant execute on function public.organization_members(uuid) to authenticated;

comment on function public.organization_members(uuid) is
  'Lists auth-backed users and invite status for memberships visible to the current admin scope.';

commit;
