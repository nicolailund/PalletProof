# PalletProof enclosure prototype

Dette er en første mekanisk prototype til en samlet lager-kasse med:

- Raspberry Pi 5
- SparkFun SEN-18088 2D Barcode Scanner Breakout
- Raspberry Pi Camera Module 3

Designet er lavet som en praktisk to-delt printbar kapsling:

- `stl/palletproof_enclosure_base.stl` - bund med frontvinduer, Pi-standoffs, scanner-/kameraholdere og vægflange.
- `stl/palletproof_enclosure_lid.stl` - låg med ventilationsslidser og skrueslots.
- `stl/palletproof_wall_mount_plate.stl` - valgfri separat montageplade.
- `stl/palletproof_enclosure_assembly_preview.stl` - samlet visningsmodel, ikke den anbefalede printfil.

## Mekanisk udtryk

Kassen er bevidst lavet lidt større end elektronikken, så den virker som et robust lagerprodukt og ikke som en åben prototype:

- hævet front omkring scanner- og kameravindue
- lukket bund og sider
- ventilationsslidser over, ved siden af og under Pi 5
- intern kabelplads til USB-C, CSI-kabel og trigger-ledninger
- vægflange/montagepunkter bagpå
- M2-gennemføringer og M2-møtriklommer til elektronikmontage

## Printforslag

- Materiale: PETG eller ASA. PLA kan bruges til prototype, men er mindre egnet i varme/sol/industrielt miljø.
- Lag: 0,2 mm.
- Vægge: mindst 4 perimeter.
- Infill: 30-40%.
- Bund: print med bunden nedad.
- Låg: print med ydersiden opad.
- Montageplade: print fladt.

## Første kontrolmål efter print

Kontroller disse punkter, før der printes en pæn version:

- Raspberry Pi 5 sidder på standoffs uden at HDMI/USB/Ethernet presses mod kassen.
- Pi 5 active cooler har fri luft over blæseren.
- Ventilationsslidser i låg, side og bund er åbne efter slicing og ikke fyldt af support.
- Scannerens optik ligger frit i det venstre frontvindue.
- SEN-18088 breakoutet ligger fladt i bunden og er roteret, så den korte scannerende kigger frem gennem frontåbningen; USB-C-enden ligger længere inde i kassen.
- Raspberry Pi 5 er placeret mod højre, så scannerprintet kan have sin fulde længde bag fronten uden at ramme Pi'en.
- Camera Module 3-linsen er centreret i det højre frontvindue.
- Camera Module 3 kan monteres enten normalt eller roteret 90 grader, hvis hele kassen monteres på højkant.
- USB-C-kablet til scanneren kan ligge uden skarp bukning.
- USB-C-strømkablet kan komme ind fra højre side og fastholdes med kabelbinder/trækaflastning.
- CSI-kablet til kameraet kan føres uden at blive klemt af låget.
- GND/TRIG-ledningerne har aflastning og bliver ikke revet ud.

## Montageforslag

På lageret bør kassen monteres på en lille justerbar vinkelarm eller maskinbeslag ved folieringsmaskinen. En fast vinkel er bedre end et fleksibelt kamerastativ, fordi scanner og kamera skal ramme samme zone hver gang.

Forslag:

- sort PETG/ASA-kasse
- klar polycarbonatplade foran scanner- og kameravinduer, hvis der er støv eller pallefilm i luften
- M4-skruer til vægbeslag
- M2-skruer og M2-møtrikker til låg og interne print
- USB-C-kabelgennemføring med indvendig trækaflastning på højre side

## Kameraretning

Løsningen forventes ofte monteret på højkant på siden af en folieringsmaskine. Derfor har kameraholderen M2-punkter til både normal og 90-graders roteret Camera Module 3-montage omkring samme linsecenter.

Hvis den fysiske montage giver et roteret videobillede, bør det løses i softwarekonfigurationen frem for at printe en ny kasse. Den mekaniske prioritet er, at linsen har frit udsyn, og at CSI-kablet ikke klemmes.

## M2 montage

Elektronikken er tænkt fastgjort med gennemgående M2-skruer og almindelige M2-møtrikker:

- Raspberry Pi 5: fire M2-standoffs i bunden.
- SEN-18088 breakout: to M2-mounts ved SparkFuns egne bageste stand-off-huller.
- Camera Module 3: fire M2-mounts, brug de huller der passer til valgt retning.
- Låg: M2-skruer ned i hjørneposter med M2-møtriklommer.

Møtriklommerne er lavet med lidt tolerance til FDM-print. Første print bør bruges til at kontrollere om de passer til de konkrete M2-møtrikker.

## Vigtige antagelser

Målene bygger på officielle/reference-mål:

- Raspberry Pi 5: 85 x 56 mm boardklasse med standard Raspberry Pi mounting hole-layout.
- Raspberry Pi Camera Module 3: 25 x 24 x 11,5 mm.
- SparkFun SEN-18088 breakout: 44,45 x 25,4 mm.
- SparkFun SEN-18088 stand-off-huller: aflæst fra SparkFuns Eagle boardfil.

Den første printversion bør forventes at skulle justeres efter den konkrete active cooler, USB-C-kabeltype, kameraretning, kameravinkel og ønsket afstand til stregkoden.
