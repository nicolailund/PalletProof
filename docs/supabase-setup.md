# Supabase setup for PalletProof

## Projektvalg

Opret projektet i en EU-region. For danske lagre er `Central EU (Frankfurt)` eller en specifik EU-region som Frankfurt, Stockholm, Paris eller Ireland et fornuftigt udgangspunkt. Vælg ikke en US-region til produktionsdata, hvis videoerne kan indeholde personoplysninger.

Start med Pro-plan til produktion. Free-plan er fin til eksperimenter, men ikke til drift, fordi begrænsninger på storage, uploadstørrelser, logs og inaktivitet hurtigt bliver et problem.

## Security defaults

Gør dette fra starten:

- Slå Row Level Security til på alle app-tabeller.
- Lav organization/site-baserede policies, så lager A aldrig kan læse lager B.
- Brug Supabase Auth til admin-login.
- Brug aldrig `service_role` key i browseren eller på Raspberry Pi-enheder.
- Lad Pi-enheder tale med vores backend/device API, ikke direkte med Supabase med admin-nøgler.
- Brug private buckets, hvis Supabase Storage bruges til video.
- Del videoer via tidsbegrænsede links, ikke public buckets.

## Lokale credentials til udvikling

Hvis Codex skal køre migrationer eller backend-test mod Supabase, så læg credentials i en lokal fil, der ikke committes:

```bash
secrets/supabase.env
```

Typiske værdier:

```text
SUPABASE_URL=https://PROJECT_ID.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
DATABASE_URL=postgresql://postgres.PROJECT_ID:DB_PASSWORD@aws-...supabase.com:6543/postgres
```

`SUPABASE_URL` og `SUPABASE_ANON_KEY` er klientoplysninger. `SUPABASE_SERVICE_ROLE_KEY` og `DATABASE_URL` er hemmeligheder og skal roteres, hvis de deles udenfor den lokale maskine.

## Video storage

Supabase Storage kan bruges til MVP og har signed upload/download flows. Hvis videoerne bliver mange eller store, bør vi dog vurdere dedikeret object storage:

- Supabase Storage: enklest, samme platform som database/auth.
- AWS S3 i EU-region: stærk compliance- og regionkontrol.
- Cloudflare R2: god økonomi ved mange downloads, men region-/dataresidencykrav skal vurderes konkret.

Databasen skal kun gemme metadata om videoen. Selve `.mp4`-filen skal ligge i object storage.

## Første schema

Start med disse tabeller:

- `organizations`
- `sites`
- `devices`
- `device_events`
- `videos`
- `video_shares`
- `profiles`
- `memberships`
- `audit_log`

`videos` skal have organization/site/device references, ordrenummer, storage path, status, varighed, filstørrelse og timestamps.

## Ting der skal besluttes før produktion

- Retention: fx 90 eller 180 dage.
- Hvem må oprette share-links.
- Standard udløbstid for share-links.
- Om kunder skal kunne downloade video eller kun afspille den.
- Backup/PITR-niveau.
- Om video storage skal være Supabase Storage, S3 eller R2.
- Om lagerpartneren kræver databehandleraftale, EU-only storage eller særskilt audit log.
