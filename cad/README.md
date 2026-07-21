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
- ventilationsslidser over Pi 5
- intern kabelplads til USB-C, CSI-kabel og trigger-ledninger
- vægflange/montagepunkter bagpå

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
- Scannerens optik ligger frit i det venstre frontvindue.
- Camera Module 3-linsen er centreret i det højre frontvindue.
- USB-C-kablet til scanneren kan ligge uden skarp bukning.
- CSI-kablet til kameraet kan føres uden at blive klemt af låget.
- GND/TRIG-ledningerne har aflastning og bliver ikke revet ud.

## Montageforslag

På lageret bør kassen monteres på en lille justerbar vinkelarm eller maskinbeslag ved folieringsmaskinen. En fast vinkel er bedre end et fleksibelt kamerastativ, fordi scanner og kamera skal ramme samme zone hver gang.

Forslag:

- sort PETG/ASA-kasse
- klar polycarbonatplade foran scanner- og kameravinduer, hvis der er støv eller pallefilm i luften
- M4-skruer til vægbeslag
- M3-skruer til låg og interne print
- kabelgennemføring med trækaflastning på højre side

## Vigtige antagelser

Målene bygger på officielle/reference-mål:

- Raspberry Pi 5: 85 x 56 mm boardklasse med standard Raspberry Pi mounting hole-layout.
- Raspberry Pi Camera Module 3: 25 x 24 x 11,5 mm.
- SparkFun SEN-18088 breakout: 44,45 x 25,4 mm.

Den første printversion bør forventes at skulle justeres efter den konkrete active cooler, USB-C-kabeltype, kameravinkel og ønsket afstand til stregkoden.
