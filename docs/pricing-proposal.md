# Prisforslag for PalletProof

Dette er et B2B launch-prisforslag ekskl. moms. Tallene er sat efter værdien for lager/kunde, ikke efter rå storage-kost alene.

## Anbefalet prisstruktur

| Komponent | Forslag | Kommentar |
| --- | ---: | --- |
| Hardware opstart pr. enhed | 4.995 DKK engangsbeløb | Dækker Pi, kamera, scanner, kabinet, kabler, klargøring, test, emballage og margin. Onsite montering kan faktureres separat. |
| Service fee pr. site | 1.495 DKK/md | Inkl. portal, support, updates, overvågning, delingslinks og 250 GB video-storage. |
| Softwarelicens pr. aktiv enhed | 249 DKK/enhed/md | Dækker software, device management, heartbeat, rollout, support og løbende forbedringer. |
| Ekstra storage | 2,50 DKK/GB/md | Sælg gerne i pakker af 100 GB = 250 DKK/md for enklere fakturering. |

Jeg har også seedet disse tal i Supabase-priskataloget, men kun hvis en pris stadig stod til 0. Senere manuelle prisændringer bliver derfor ikke overskrevet af migrationen.

## Hvorfor disse priser

Hardware bør ikke sælges til ren kostpris. Enheden er et industrielt produkt med test, konfiguration, garanti, udskiftning, support og ansvar. Med Raspberry Pi 5, Camera Module 3, SparkFun SEN-18088, strøm, SD/SSD, kabler og kabinet lander ren stykliste typisk i et niveau hvor 4.995 DKK giver en rimelig buffer til klargøring og fejlretning.

Site fee bør dække det, der ikke skalerer direkte med antal enheder: portal, adgangsstyring, drift, support, compliance, storage-grundpakke og delingsflow. 1.495 DKK/md er lavt nok til et lager med flere maskiner, men højt nok til at undgå at små kunder bliver underskud.

Device license gør løsningen fair for lagre med 1 maskine vs. 30 maskiner. 249 DKK/md pr. enhed er et godt launch-niveau, fordi produktet kan spare én enkelt tvist om manglende varer, og det alene kan betale flere måneders licens.

Ekstra storage skal prissættes over rå cloudpris. I sælger ikke GB alene; I sælger sikker opbevaring, adgangsstyring, retention, privacy processing, support og fremfinding af dokumentation.

## Eksempel

Et lager med 20 folieringsmaskiner:

- Hardware opstart: 20 x 4.995 = 99.900 DKK engangsbeløb.
- Månedligt site fee: 1.495 DKK.
- Månedlig device license: 20 x 249 = 4.980 DKK.
- Total månedlig base: 6.475 DKK/md inkl. 250 GB storage.
- Ekstra 500 GB storage: 1.250 DKK/md.

## Mulige pakker

| Pakke | Pris | Indeholder |
| --- | ---: | --- |
| Starter | 1.495 DKK/site/md + 299 DKK/enhed/md | Til 1-5 enheder, 100 GB inkluderet. |
| Warehouse | 1.495 DKK/site/md + 249 DKK/enhed/md | Standardpris, 250 GB inkluderet. |
| Enterprise | Fra 4.995 DKK/site/md + 199 DKK/enhed/md | 20+ enheder, SSO/SLA/auditkrav og individuel aftale. |

Min anbefaling er at starte simpelt med Warehouse-modellen og kun bruge pakkerne kommercielt, hvis kunderne beder om det.

## Ting der bør faktureres separat

- Onsite montering og rejsetid.
- 4G/5G abonnement/SIM.
- Særlige monteringsbeslag eller kabinetvarianter.
- Dataudtræk eller manuel videosøgning som service.
- Lang retention, fx 12-24 måneder.
- Dedikeret EU-processing eller høj volumen privacy processing, hvis en kunde genererer meget video.

## Kilder tjekket 2026-07-24

- Supabase Pro: 25 USD/md, 100 GB file storage inkluderet, derefter 0,0213 USD/GB: https://supabase.com/pricing
- Cloudflare R2: 0,015 USD/GB-md standard storage, ingen R2 egress fee: https://developers.cloudflare.com/r2/pricing/
- Raspberry Pi 5 prisniveau efter 2025 prisændring: https://www.raspberrypi.com/news/1gb-raspberry-pi-5-now-available-at-45-and-memory-driven-price-rises/
- Raspberry Pi Camera Module 3: https://www.raspberrypi.com/news/new-autofocus-camera-modules/
- SparkFun SEN-18088: https://learn.sparkfun.com/tutorials/2d-barcode-scanner-breakout-hookup-guide/all
