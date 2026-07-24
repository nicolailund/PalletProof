# Raspberry Pi palle-video

MVP til en Raspberry Pi 5 med kamera ved en folieringsmaskine:

1. Lageret scanner ordrenummeret med en SEN-18088 2D barcode scanner.
2. Pi'en modtager ordrenummeret og giver et lyd-/lys-signal.
3. Pi'en optager video, mens pallen drejer.
4. Optagelsen stopper, når pallen har stået stille i et konfigureret antal sekunder.
5. Videoen gemmes lokalt i en kø og uploades til FTP/FTPS med enhedsserienummer, ordrenummer, dato og tid i filnavnet.
6. Valgfri privacy-processering kan sløre detekterede ansigter og faste billedområder inden upload.

## Vigtige designvalg

- **Lokal spool-kø først:** Netværk på lageret vil fejle fra tid til anden. Derfor er optagelsen færdig og gemt lokalt, før upload forsøges. Upload genprøves automatisk.
- **WiFi/mobil behandles som netværk:** Selve appen er ligeglad med om forbindelsen er WiFi, Ethernet eller 4G/5G modem. Raspberry Pi OS bør sættes op med NetworkManager til automatisk failover.
- **Provisioning før drift:** I produktion kan enheden starte i låst tilstand. Første gyldige scan skal være en PalletProof provisioning-QR, som binder enheden til serienummer, kunde og site.
- **FTPS anbefales:** Almindelig FTP sender login og data ukrypteret. Brug `protocol = "ftps"` hvis serveren understøtter det.
- **GDPR:** Den mest driftssikre løsning er at placere kameraet, så personer ikke kommer i billedet. Software-sløring er et ekstra sikkerhedslag, ikke en garanti.

## Hardwareforslag

- Raspberry Pi 5 med aktiv køling.
- SparkFun SEN-18088 2D Barcode Scanner Breakout til ordrenummer-scan.
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
- `hardware_scanner.device`
- `hardware_scanner.accepted_pattern`
- `device.provisioning_required`
- `motion.roi`

`motion.roi` er den del af billedet, hvor pallen forventes at dreje. Formatet er normaliseret:

```toml
roi = [0.10, 0.10, 0.80, 0.80]
```

Det betyder `x`, `y`, `bredde`, `højde`, hvor `1.0` er hele billedets bredde/højde.

## Provisioning og enhedsidentitet

Når `device.provisioning_required = true`, virker enheden ikke som almindelig palleoptager, før den har scannet en PalletProof provisioning-QR med hardware-scanneren. QR-koden indeholder:

- serienummer for enheden
- kunde-/lagerreference
- site eller lokation
- aktiveringstoken
- WiFi-navn og WiFi-password
- valgfri API-base-URL og udløbstid

Den kompakte QR-værdi bruger formatet `PALLETPROOF1.<base64url-json>`, så den kan læses sikkert af SEN-18088 uden at udvide de tilladte tegn for normale ordrescans. Hardware-scanneren skal derfor acceptere lange værdier:

```toml
[hardware_scanner]
max_chars = 512
```

Efter god provisioning gemmes en lokal `device_identity.json`. Den gemmer serienummer, kunde/site og aktiveringstidspunkt, men ikke WiFi-password. Når backend-delen er på plads, bør aktiveringstokenet udskiftes med egentlige device credentials fra API'et, og WiFi-oplysningerne bør lægges i Raspberry Pi OS/NetworkManager i stedet for appens identity-fil.

Til prototypetest uden backend/QR kan provisioning slås fra:

```toml
[device]
provisioning_required = false
serial_number = "PP-DEV-001"
```

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

## SEN-18088 hardware-scanner

Anbefalet tilslutning er USB:

1. Sæt SEN-18088 i Raspberry Pi'en med USB-C.
2. Scanneren kan bruges i enten USB keyboard/HID-tilstand eller USB-COM/Virtual COM-tilstand. Appen prøver begge med `mode = "auto"`.
3. Find den port Pi'en ser:

```bash
ls -l /dev/input/by-id/*event-kbd /dev/serial/by-id/ /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

4. Sæt gerne den konkrete port i `config.toml`, især hvis Pi'en også har USB 4G/5G-modem:

```toml
[hardware_scanner]
enabled = true
mode = "auto"
device = "/dev/serial/by-id/usb-SCANNER_NAVN"
baudrate = 115200
```

`device = "auto"` virker ofte fint. Hvis den står i HID-tilstand, vil porten ligne `/dev/input/by-id/...event-kbd`; hvis den står i COM-tilstand, vil den typisk ligne `/dev/serial/by-id/...` eller `/dev/ttyACM0`. En konkret `/dev/input/by-id/...` eller `/dev/serial/by-id/...` er mest stabilt i drift, især hvis Pi'en også har 4G/5G-modem.

Til test:

```bash
sudo journalctl -u pallet-video -f
```

Scan derefter en ordrestregkode. Loggen skal vise `Hardware scanner read barcode/order number` og derefter `Starting recording for order ...`. SEN-18088 har egen buzzer/status-LED ved korrekt decode; appens statuslys/ACT-LED blinker først, når Pi-servicen faktisk har modtaget og godkendt værdien.

Hvis scanneren skriver ordrenummeret som tastaturinput i PuTTY/browseren, står den i USB keyboard/HID-tilstand. Appen kan læse den tilstand direkte via `/dev/input/...`, men servicebrugeren skal have adgang til input-enheden. På Pi'en løses det typisk ved at tilføje `palletcam` til gruppen `input` og genstarte servicen.

### Automatisk trigger hver 2. sekund

SEN-18088 står normalt i trigger mode: den scanner kun, når knappen trykkes, eller når `TRIG`-pinnen trækkes til GND. Pi'en kan derfor selv trykke elektronisk på triggeren, mens den venter på en ordre.

USB-C-kablet bliver siddende og bruges stadig til data. Tilføj kun disse to ledninger:

```text
SEN-18088 GND  -> Pi GND, fysisk pin 14
SEN-18088 TRIG -> Pi GPIO23, fysisk pin 16
```

Konfiguration:

```toml
[hardware_scanner]
trigger_gpio_enabled = true
trigger_gpio_pin = 23
trigger_interval_seconds = 2.0
trigger_pulse_seconds = 0.15
trigger_active_high = false
```

`trigger_active_high = false` betyder, at Pi'en laver et kort aktivt lavt signal, svarende til at trigger-knappen trækker `TRIG` mod GND. Appen pulser kun triggeren, når den står klar til scan; under optagelse er pulsen slukket.

Alternativet er at konfigurere scanneren til continuous/presentation mode med dens settings-barcodes. GPIO-trigger er dog mere kontrolleret i denne løsning, fordi vi selv bestemmer, at den kun scanner, når systemet faktisk venter på en ny ordre.

### UART som reserve

USB er enklest og mest støjsikkert. Hvis USB ikke kan bruges, kan SEN-18088 forbindes direkte til Pi'ens UART med 3.3V TTL:

```text
SEN-18088 3.3V -> Pi 3V3, fysisk pin 1 eller 17
SEN-18088 GND  -> Pi GND, fysisk pin 6, 9, 14, 20, 25, 30, 34 eller 39
SEN-18088 TX   -> Pi RXD0/GPIO15, fysisk pin 10
SEN-18088 RX   -> Pi TXD0/GPIO14, fysisk pin 8
```

På SparkFun-breakoutets header skal du følge silketrykket på printet: `STAT TRIG 3.3V RX TX GND`. TX og RX krydses altid mellem scanner og Pi. Aktiver derefter Pi'ens serial port uden login-shell:

```bash
sudo raspi-config
```

Vælg `Interface Options` -> `Serial Port`: login shell = `No`, serial hardware = `Yes`.

## Kamerabaseret stregkodelæsning som fallback

Kamera-scanning er som standard slået fra, fordi SEN-18088 er mere stabil og bruger langt mindre CPU. Hvis kameraet skal bruges som fallback, kan det aktiveres:

```toml
[barcode]
enabled = true
```

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

Mens servicen venter på barcode, skriver den periodisk `SCAN_STATUS` i loggen. Den linje viser om kamera-loopet lever, om hardware-scanneren er forbundet, hvilken port der bruges, og hvor mange hardware-scans der er modtaget. Hvis kamera-scanning er slået til, bruges den udvidede `BARCODE_SCAN_STATUS` med både hardware- og kamera-scan-tal.

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

## Software updates fra GitHub

Pi'en kan poll'e en update-manifest i GitHub og installere ny kode, når enheden er idle. Flowet er slået fra som standard:

```toml
[software_update]
enabled = true
manifest_url = "https://raw.githubusercontent.com/nicolailund/PalletProof/main/updates/palletproof-update.json"
repository_dir = "."
install_command = "bash scripts/install_from_github.sh"
night_start_hour = 2
night_end_hour = 4
```

Når en GitHub-ændring skal rulles ud, ændres `updates/palletproof-update.json`:

```json
{
  "schema_version": 1,
  "update_id": "2026-07-23-scanner-fix-001",
  "policy": "force",
  "target_ref": "main",
  "target_commit": "",
  "version": "0.1.0"
}
```

`policy` kan være:

- `force`: installeres så snart enheden er idle og ikke optager video.
- `night`: installeres kun når enheden er idle i nattevinduet, fx 02-04.

Brug ikke Git force-push til dette. Det er en rollout-politik i manifestet, ikke en omskrivning af Git-historik. Hver rollout skal have et nyt `update_id`, ellers ignorerer enheden manifestet som allerede installeret.

Installationsscriptet bruger `git merge --ff-only`, så det fejler i stedet for at overskrive lokale kodeændringer. `config.toml` bør derfor holdes udenfor Git på Pi'en, mens kildekoden holdes ren.

## Filnavne

Videoer navngives sådan:

```text
SERIENUMMER_ORDRENUMMER_20260705_153012.mp4
```

Eksempel:

```text
PP-000123_ORD-456_20260705_153012.mp4
```

Hvis provisioning er slået fra, bruges `device.serial_number` som fallback-serienummer.

Hvis privacy-processering er slået til, uploades den behandlede video med samme navn. Råvideoen slettes efter behandlingen, hvis `privacy.delete_source_after_processing = true`.

Hvis privacy-processering fejler, uploades råvideoen ikke automatisk. Den flyttes til `data/failed`, så den kan vurderes manuelt.

## Scanner sleep time

Adminportalen kan sætte et aktivt tidsvindue pr. enhed. Pi'en henter schedule via Supabase heartbeat og pulser kun SEN-18088 triggeren i det aktive vindue. Hvis en optagelse allerede er startet, stoppes den ikke af sleep time; sleep time gælder kun nye scanninger.

Hvis cloud ikke er aktivt, eller der ikke er sat schedule på enheden, er scanneren altid aktiv som fallback.

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
