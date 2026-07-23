begin;

drop policy if exists "Owners and admins can manage activation tokens" on public.device_activation_tokens;
create policy "Owners and admins can manage activation tokens"
on public.device_activation_tokens for all
to authenticated
using (
  exists (
    select 1
    from public.devices d
    where d.id = device_activation_tokens.device_id
      and app.is_org_admin(d.organization_id)
  )
)
with check (
  exists (
    select 1
    from public.devices d
    where d.id = device_activation_tokens.device_id
      and app.is_org_admin(d.organization_id)
  )
);

commit;
