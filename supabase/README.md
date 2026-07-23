# Supabase setup

Project URL:

```text
https://aybniokguhhvudwkewbe.supabase.co
```

## Hvad migrationen opretter

`migrations/20260723140000_initial_palletproof_schema.sql` opretter:

- organizations, sites og memberships
- devices og device activation tokens
- device events og heartbeat/status-grundlag
- video metadata og private video storage bucket
- video share links og access log
- software rollouts med `force`/`night`
- audit log
- Row Level Security policies for multi-tenant adgang

## Credentials

Giv ikke Supabase account password til Codex.

Hvis migrationen skal køres direkte herfra, læg midlertidige credentials i:

```text
secrets/supabase.env
```

Eksempel:

```text
SUPABASE_URL=https://aybniokguhhvudwkewbe.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
DATABASE_URL=postgresql://postgres.aybniokguhhvudwkewbe:DB_PASSWORD@aws-...supabase.com:6543/postgres
```

Til selve migrationen er `DATABASE_URL` bedst. Den findes i Supabase Dashboard under Project Settings -> Database -> Connection string. Brug pooler/transaction URI eller direct URI, alt efter hvad dashboardet anbefaler for dit projekt.

Efter migrationen er kørt, bør database password/service role key roteres, hvis de har været delt udenfor din lokale maskine.

## Manuel kørsel

Hvis du vil køre migrationen i SQL Editor, kan hele SQL-filen indsættes og køres som én transaktion.

Hvis `DATABASE_URL` ligger i miljøet:

```bash
psql "$DATABASE_URL" -f supabase/migrations/20260723140000_initial_palletproof_schema.sql
```

## Første admin

Når første admin-bruger er oprettet via Supabase Auth, skal vedkommende have en membership. Det kan gøres med service role/backend eller en engangs-SQL i dashboardet, fx:

```sql
insert into public.organizations (name, slug)
values ('SweetSpot', 'sweetspot')
returning id;

insert into public.sites (organization_id, name, slug)
values ('ORGANIZATION_ID_HER', 'Rhenus Horsens', 'rhenus-horsens')
returning id;

insert into public.memberships (organization_id, site_id, user_id, role)
values ('ORGANIZATION_ID_HER', null, 'AUTH_USER_ID_HER', 'owner');
```
