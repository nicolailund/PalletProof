# PalletProof Admin

React/Vite admin-portal til PalletProof.

## Lokal konfiguration

Opret `web/.env.local`:

```text
VITE_SUPABASE_URL=https://aybniokguhhvudwkewbe.supabase.co
VITE_SUPABASE_ANON_KEY=...
```

`VITE_SUPABASE_ANON_KEY` er Supabase `anon public` key. Den må bruges i browseren, fordi adgang styres med Supabase Auth og Row Level Security.

## Funktioner i første version

- login med Supabase Auth
- overblik over organization/site
- enhedsliste
- opret enhed
- generér provisioning-QR med WiFi og activation token
- videooversigt og basis for share-token
- software rollout-register med `force` og `night`

## Kør lokalt

```bash
npm install
npm run dev
```

## Build

```bash
npm run build
```
