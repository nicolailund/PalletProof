# Raspberry Pi palle-video

MVP til en Raspberry Pi 5 med kamera ved en folieringsmaskine:

1. Lageret viser en stregkode til kameraet.
2. Pi'en læser ordrenummeret og giver et lydsignal.
3. Pi'en optager video, mens pallen drejer.
4. Optagelsen stopper, når pallen har stået stille i et konfigureret antal sekunder.
5. Videoen gemmes lokalt i en kø og uploades til FTP/FTPS med ordrenummer, dato og tid i filnavnet.
6. Valgfri privacy-processering kan sløre detekterede ansigter og faste billedområder inden upload.

## Vigtige designvalg

- **Lokal spool-kø først:** Netværk på lageret vil fejle fra tid til anden. Derfor er optagelsen færdig og gemt lokalt, før upload forsøges. Upload genprøves automatisk.
- **WiFi/mobil behandles som netværk:** Selve appen er ligeglad med om forbindelsen er WiFi, Ethernet eller 4G/5G modem. Raspberry Pi OS bør sættes op med NetworkManager til automatisk failover.
- **FTPS anbefales:** Almindelig FTP sender login og data ukrypteret. Brug `protocol = "ftps"` hvis serveren understøtter det.
- **GDPR:** Den mest driftssikre løsning er at placere kameraet, så personer ikke kommer i billedet. Software-sløring er et ekstra sikkerhedslag, ikke en garanti.

## Hardwareforslag

- Raspberry Pi 5 med aktiv køling.
- Raspberry Pi Camera Module 3 eller HQ-kamera, afhængigt af afstand og lys.
- Fast montering på siden af folieringsmaskinen.
- Ekstra LED-lys hvis lagerlyset varierer.
- Panelmonteret statuslampe eller RGB-LED: grøn = klar, gul = stregkode læst, rød = optager/færdiggør.
- Valgfri buzzer på GPIO eller USB-/jack-højttaler, hvis lydfeedback giver mening.
- Industrielt microSD eller SSD via USB til lokal kø.
- Valgfrit 4G/5G USB-modem eller router, hvis WiFi er ustabilt.

## Installation på Raspberry Pi OS

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg python3-picamera2 python3-opencv python3-zxing-cpp python3-paramiko
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -e . --no-deps
```

`--system-site-packages` bruges bevidst, fordi OpenCV, Picamera2 og ZXing er bedre og hurtigere installeret som Raspberry Pi/Debian-pakker end som pip-builds på selve Pi'en.

## Konfiguration

Kopier eksempelkonfigurationen:

```bash
cp config.example.toml config.toml
```

Ret især:

- `upload.protocol`
- `upload.host`
- `upload.port`
- `upload.username`
- `upload.password`
- `upload.remote_dir`
- `barcode.accepted_pattern`
- `barcode.roi`
- `motion.roi`

`motion.roi` er den del af billedet, hvor pallen forventes at dreje. Formatet er normaliseret:

```toml
roi = [0.10, 0.10, 0.80, 0.80]
```

Det betyder `x`, `y`, `bredde`, `højde`, hvor `1.0` er hele billedets bredde/højde.

## Kør lokalt

```bash
pallet-video --config config.toml
```

Til udvikling uden Pi-kamera kan OpenCV-kamera vælges:

```toml
[camera]
backend = "auto"
opencv_device = 0
```

`backend = "auto"` vælger Raspberry Pi Camera Module via Picamera2/libcamera, hvis et internt CSI-kamera er detekteret. Hvis der ikke findes et internt kamera, bruges USB-kamera via OpenCV/V4L2.

## Kamerabaseret stregkodelæsning

Barcode-læsningen prøver flere billedvarianter, så labelen ikke behøver at være perfekt vandret:

- `barcode.roi` begrænser scanningen til den del af billedet, hvor lageret viser labelen.
- `barcode.rotation_degrees` prøver normale retninger plus moderate skæve vinkler. Flere vinkler kan hjælpe, men koster meget CPU.
- `barcode.formats` begrænser dekoderen til forventede barcode-typer. DataBar er som standard udeladt, fordi den gav falske fund på støj/reflekser i testbilleder.
- `barcode.scan_scales` kan opskalere billedet, hvis labelen er lille eller langt fra kameraet. Start med `[1.0]` for lav CPU.
- `barcode.preprocess` prøver ekstra gråskala-, kontrast- og threshold-varianter. Brug kun dette, hvis de faktiske labels ikke kan læses uden.
- `barcode.confirm_read_count = 2` kræver samme gyldige kode på to frames. Ved 30 fps føles det stadig øjeblikkeligt, men dæmper enkelt-frame fejllæsninger.
- `barcode.duplicate_suppress_seconds` forhindrer, at samme synlige label starter en ny optagelse straks efter stop.
- `barcode.ambient_suppress_seconds` ignorerer koder, der allerede er synlige lige efter service-start eller lige efter en optagelse.
- `barcode.validate_gs1_ai01_check_digit` validerer checkcifferet for GS1 AI(01)-værdier.

Barcode-scanningen kører på kameraets preview-stream. `camera.preview_width` og `camera.preview_height` bør derfor ikke sættes for lavt; `1280x720` er et bedre udgangspunkt end `640x360` til håndholdte labels. For Raspberry Pi Camera Module 3 bruges `camera.autofocus_range = "full"` og `camera.autofocus_speed = "fast"` som udgangspunkt, så kameraet hurtigere kan stille skarpt på labels tæt på linsen.

Standardfilteret tillader også Code 39-specialtegn som `$`, `/`, `+` og `%` samt GS1-lignende parentesformat, fx `(01)08584012360472`. AI(01)-værdier valideres som GTIN-14, når `barcode.validate_gs1_ai01_check_digit = true`. Tegn, der ikke er sikre i filnavne, bliver saniteret væk i videofilnavnet, så filen ender med et sikkert navn som `01_08584012360472_YYYYMMDD_HHMMSS.mp4`.

Til drift bør `barcode.roi`, lys, afstand og fokus testes med de faktiske lagerlabels. Den aggressive scanning kan også fange produktstregkoder på pallen, hvis de er synlige. Hvis CPU-belastningen bliver for høj, er første justering at snævre `barcode.roi` ind og reducere `barcode.scan_scales` eller `barcode.rotation_degrees`.

Mens servicen venter på barcode, skriver den periodisk `BARCODE_SCAN_STATUS` i loggen. Den linje viser om kamera-loopet lever, hvor mange scan-jobs der er sendt/færdige, og hvor længe den aktuelle scan har kørt.

## Midlertidig scan-feedback med Piens ACT-LED

Hvis der ikke er monteret buzzer eller ekstern lampe endnu, kan appen blinke Raspberry Piens indbyggede grønne ACT-LED, når en stregkode er godkendt.

```toml
[status_light]
enabled = true
backend = "act_led"
scan_flash_seconds = 0.8
sysfs_led_name = "ACT"
restore_trigger = "mmc0"
```

ACT-LEDen sidder på selve Pi-boardet. Den bliver kun overtaget kort under scan-kvitteringen og sættes derefter tilbage til normal SD-kort-aktivitet.

## Statuslampe på GPIO

`status_light` bruger to GPIO-udgange:

- grøn LED-kanal = idle/klar
- rød LED-kanal = optager
- rød + grøn samtidig = gul, vist kort efter at en stregkode er læst

Standardkonfigurationen bruger BCM-nummerering:

```toml
[status_light]
enabled = true
backend = "gpio"
red_gpio_pin = 27
green_gpio_pin = 17
# Valgfri: brug kun hvis lampen har separat gul indgang.
# yellow_gpio_pin = 22
active_high = true
scan_flash_seconds = 0.4
```

Direkte prototype med en lille common-cathode RGB-LED eller bicolor rød/grøn LED:

```text
GPIO17 / fysisk pin 11 -> 330-470 ohm -> grøn LED-ben
GPIO27 / fysisk pin 13 -> 330-470 ohm -> rød LED-ben
GND    / fysisk pin 14 -> fælles cathode/GND
```

Brug én modstand pr. farvekanal. Til en panelmonteret 12V/24V industrilampe må GPIO ikke drive lampen direkte; brug transistor/MOSFET/ULN-driver eller et optoisoleret driver-modul mellem Pi og lampen.

Hvis industrilampen har en separat gul indgang i stedet for at blande rød og grøn, sæt `yellow_gpio_pin` og brug samme driverprincip for den tredje kanal.

## Live kamera-preview

Til fejlfinding kan appen vise samme preview-feed, som barcode-scanneren bruger:

```toml
[preview]
enabled = true
host = "0.0.0.0"
port = 8080
max_fps = 5.0
width = 960
jpeg_quality = 70
```

Åbn derefter `http://PI-IP:8080` fra en browser på samme netværk, fx `http://192.168.1.178:8080`. Previewen er ikke passwordbeskyttet og bør kun bruges på et internt netværk.

## Systemd service

Tilpas `systemd/pallet-video.service`, så `WorkingDirectory`, `ExecStart` og bruger passer til Pi'en.

Installér derefter:

```bash
sudo cp systemd/pallet-video.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pallet-video
sudo journalctl -u pallet-video -f
```

## Filnavne

Videoer navngives sådan:

```text
ORDRENUMMER_20260705_153012.mp4
```

Hvis privacy-processering er slået til, uploades den behandlede video med samme navn. Råvideoen slettes efter behandlingen, hvis `privacy.delete_source_after_processing = true`.

Hvis privacy-processering fejler, uploades råvideoen ikke automatisk. Den flyttes til `data/failed`, så den kan vurderes manuelt.

## Upload

`upload.protocol` kan være:

- `sftp` - anbefalet, hvis serveren understøtter SSH/SFTP.
- `ftps` - FTP over TLS.
- `ftp` - kun hvis der ikke er andre muligheder.

Til SFTP bruges `python3-paramiko` på Pi'en.

## Drift og fejlhåndtering

- Filer i `data/pending` venter på upload.
- Filer i `data/uploaded` er uploadet, hvis `upload.delete_after_upload = false`.
- Filer i `data/failed` kræver manuel undersøgelse.
- Upload genprøves automatisk, så længe Pi'en er tændt.
- Brug SSD eller stort industrielt SD-kort, hvis der kan være langvarigt netværksudfald.

## Ekstra WiFi-netværk

På Raspberry Pi OS med NetworkManager kan ekstra WiFi-profiler tilføjes sådan:

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name "NetvaerksNavn" ssid "NetvaerksNavn" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "WiFiPassword" \
  connection.autoconnect yes connection.autoconnect-priority 50
```

Pi'en forbinder automatisk til kendte netværk, når de er tilgængelige. En højere `connection.autoconnect-priority` vælges før en lavere, hvis flere kendte netværk er inden for rækkevidde.

## USB 4G/5G modem

Pi'en kan bruge et USB 4G/5G modem via NetworkManager og ModemManager.

Installer modem-support:

```bash
sudo apt install -y modemmanager mobile-broadband-provider-info usb-modeswitch ppp
sudo systemctl enable --now ModemManager
```

Opret mobilprofil:

```bash
sudo nmcli connection add type gsm ifname "*" con-name MobileData apn "internet" \
  connection.autoconnect yes connection.autoconnect-priority 10 \
  ipv4.method auto ipv4.route-metric 900 \
  ipv6.method auto ipv6.route-metric 900 \
  connection.metered yes
```

Hvis operatøren bruger en anden APN:

```bash
sudo nmcli connection modify MobileData gsm.apn "OPERATOER_APN"
```

Nyttige statuskommandoer:

```bash
mmcli -L
nmcli device
nmcli connection show MobileData
nmcli connection up MobileData
```

Route-metric er sat højere for mobil end WiFi, så WiFi foretrækkes når det er tilgængeligt, mens mobilforbindelsen kan bruges som fallback. Hvis WiFi er forbundet, men har dårlig eller ingen internetadgang, kan det kræve en aktiv watchdog senere for at tvinge skift til mobil.

## Næste praktiske trin

1. Test barcode-læsning med de faktiske labels fra lageret.
2. Optag testvideoer ved maskinen og justér `motion.threshold` og `motion.roi`.
3. Vælg om privacy skal klares primært med kameravinkel/fysisk afskærmning, faste masker eller ansigtsdetektion.
4. Test upload over både WiFi og mobilforbindelse.
5. Aftal lokal retention, adgang til FTP-serveren og slettepolitik.
