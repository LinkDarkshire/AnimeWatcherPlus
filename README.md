<p align="center">
  <img src="./logo_text.jpeg" alt="AnimeWatcher Plus" width="600">
</p>

<p align="center"><a href="./README.en.md">English version</a></p>

# AnimeWatcherPlus

Lokale Desktop-Anwendung zur Verwaltung einer Anime-Sammlung: erkennt Animes
in deinen Ordnern über AniDB, zeigt fehlende Folgen, sortiert und benennt
Downloads einheitlich und übergibt neue Folgen an deinen Download-Client.
Die Bibliothek kann auch auf einem Server (z. B. NAS) liegen – dann greifen
mehrere PCs und die Android-App darauf zu.

**Einrichtung von null an:** [docs/EINRICHTUNG.md](docs/EINRICHTUNG.md)

## Funktionen

- **Ordner & Scanner:** Content- und Download-Ordner in der App verwalten.
  Beim Start ein Scan, der unveränderte Dateien überspringt, danach
  Live-Überwachung. Änderungen werden erst verarbeitet, wenn ein Download
  oder Kopiervorgang fertig ist. Netzlaufwerke, die erst später erreichbar
  sind, werden automatisch nachgeholt.
- **Erkennung über AniDB:** zuerst eine vorhandene `tvshow.nfo`, sonst ein
  Abgleich des Ordnernamens mit der lokalen AniDB-Titelliste (wird alle 7
  Tage aktualisiert). Unsichere Treffer landen zur Prüfung auf „Abfragen“,
  statt geraten zu werden. Anfragen an AniDB sind gedrosselt, werden 7 Tage
  zwischengespeichert und respektieren Sperren. Nach einer Sperre setzt die
  App die liegengebliebenen Erkennungen automatisch fort.
- **AniDB-Anzeige:** In der Kopfzeile siehst du live, was gerade bei AniDB
  abgefragt wird, wie viele Aufträge offen sind und bis wann eine Sperre
  oder das Tageslimit gilt.
- **Artwork & Metadaten:** Poster, `tvshow.nfo` und Episoden-NFOs im
  Jellyfin/Kodi-Format sowie eine `aniinfo.json` mit allen AniDB-Daten im
  Anime-Ordner. Titel wahlweise englisch, romaji oder japanisch, für die
  Anzeige und für Ordnernamen getrennt einstellbar.
- **Bibliothek:** Raster mit Seiten (25/50/100 pro Seite), Volltextsuche,
  Filter nach Status, Tag und fehlenden Folgen, Detailseite mit Episoden,
  manuellen Episodennummern und Ordner-Öffnen-Knopf.
- **Fehlende Folgen:** Vergleich der AniDB-Episodenliste mit den Dateien
  auf der Platte, pro Serie und als Gesamtübersicht.
- **Sortieren & Umbenennen:** Animes aus Download-Ordnern in den
  Content-Ordner verschieben (in eine vorhandene Serie oder als neue),
  Ordner und Dateien einheitlich benennen
  (`Titel/Titel - S01E05 - Episodenname.mkv`). Untertitel und andere
  Begleitdateien wandern mit. Auf Nachfrage oder automatisch.
- **Duplikate:** dieselbe Serie in zwei Ordnern wird erkannt und zur
  Entscheidung angezeigt.
- **Wunschliste:** Animes, die du noch nicht hast, über die AniDB-Titelliste
  suchen und vormerken. Sie erscheinen nicht in der Bibliothek, bis sie in
  einem deiner Ordner auftauchen.
- **Downloads:** fehlende Folgen und Wünsche an einen Download-Client
  übergeben, mit Live-Fortschritt. Eingebaut: qBittorrent, Transmission und
  JDownloader 2 (über MyJDownloader oder Folder Watch). Such-Quellen und
  weitere Clients lassen sich als Plugins ergänzen (siehe unten).
- **Wartung:** Reparatur-Scan, der Titel, Episodennummern und Metadaten aus
  lokalen Daten wiederherstellt, ohne AniDB zu fragen.
- **Logging:** rotierende JSON-Logdatei (`logs/core.log`, 10 MB × 5 Dateien)
  zum Beilegen bei Problemen.
- **Installer & Auto-Update:** signierter NSIS-Installer; die App prüft beim
  Start auf neue Versionen in den GitHub Releases. Unter Linux als AppImage,
  das ohne Installation läuft.

## Neu in 0.3.0

- **Server-Modus:** die Bibliothek als Docker-Container auf dem NAS, dort
  wo die Dateien liegen; Desktop-Apps verbinden sich damit, Einstellungen
  und Plugins liegen zentral. Umschalten zwischen lokal und Server samt
  Umzug der Bibliothek in beide Richtungen.
- **Android-App:** Bibliothek, Wunschliste und Downloads vom Server auf dem
  Handy; Koppeln per QR-Code; Beiträge (z. B. von X) über *Teilen* direkt
  als Wunschlisten-Vorschlag.
- **Sicherheit ohne Passwörter:** Geräteschlüssel, Koppeln nur im
  Heimnetz mit Freigabe durch ein Admin-Gerät, Verschlüsselung auch im
  Heimnetz mit gemerktem Server-Zertifikat.
- Oberfläche für Handy- und Tablet-Breite (Navigation unten).
- Schritt-für-Schritt-Einrichtung: [docs/EINRICHTUNG.md](docs/EINRICHTUNG.md)
- Neuer Signierschlüssel für Updates: Wer eine selbst gebaute Version vor
  0.3.0 installiert hat, installiert 0.3.0 einmal von Hand; danach
  aktualisiert sich die App wieder selbst.

## Neu in 0.2.0

- Wunschliste, Download-Seite mit Plugins für Clients und Such-Quellen,
  Live-Fortschritt der Downloads
- qBittorrent-, Transmission- und MyJDownloader-Anbindung
- AniDB-Aktivitätsanzeige und automatisches Fortsetzen nach einer Sperre
- Bibliothek mit Seiten statt endlosem Scrollen, Seitengröße einstellbar
- Sortieren/Umbenennen nimmt Untertitel und Begleitdateien mit und löscht
  keine Dateien mehr, die nicht verschoben wurden
- „Leerer Ordner“-Abfrage nur noch für wirklich leere Ordner
- Fehlgeschlagene Aktionen werden als Meldung angezeigt
- Linux: AppImage (`build_linux.sh`) und Startskript (`dev_start.sh`)
- Releases für Windows und Linux werden automatisch auf GitHub gebaut
- Zahlreiche Fehlerbehebungen (Titelsuche, Offline-Ordner, Speicherlecks,
  Sicherheit der Desktop-Shell)

## Projektstruktur

```
core/       Python/FastAPI-Backend ("Core", läuft als Sidecar-Prozess)
shell/      Tauri-Desktop-Shell (Rust) + React-Oberfläche (shell/ui)
```

## Voraussetzungen

- Python 3.12+
- Node.js 20+
- Rust/Cargo + Tauri-CLI (`cargo install tauri-cli`) — nur für die Desktop-Shell

Unter Linux reicht `distrobox`, siehe [Linux](#linux-starten-per-skript).

## Backend einrichten & starten

```bash
cd core
python -m venv .venv
.venv/Scripts/activate   # bzw. source .venv/bin/activate unter Linux
pip install -e ".[dev]"
python -m uvicorn app.main:app --port 8000
```

Datenbank-Migrationen laufen automatisch beim Start. App-Daten liegen unter
`%APPDATA%/AnimeWatcherPlus` bzw. `~/.local/share/AnimeWatcherPlus`.

Tests: `python -m pytest` · Lint: `ruff check app tests` · Typen: `mypy app --ignore-missing-imports`

## Frontend einrichten & starten (Browser-Modus)

```bash
cd shell/ui
npm install
npm run dev
```

Erwartet den Core unter `http://127.0.0.1:8000` (siehe `.env`).
Tests: `npm run test` · Typecheck: `npx tsc -b` · Lint: `npm run lint`

## Desktop-Shell (Tauri)

```bash
cd shell
cargo tauri dev
```

oder unter Windows einfach `dev_start.bat`. Die Shell erzeugt pro Sitzung
ein Token, startet den Core aus `core/.venv` auf einem freien Port und
öffnet das Fenster, sobald er antwortet. Das ist der Entwicklungsmodus — für
einen installierbaren Build siehe unten.

## Linux: Starten per Skript

```bash
./dev_start.sh            # Desktop-App (Tauri-Fenster)
./dev_start.sh --browser  # nur Core + Oberfläche im Browser, ohne Tauri
./dev_start.sh --setup    # nur einrichten/kompilieren, nicht starten
```

Das Gegenstück zu `dev_start.bat`. Alles läuft in einem Distrobox-Container
(`awp-dev`, Fedora 44), weil Tauri unter Linux WebKitGTK-/GTK-Entwicklungs-
pakete braucht, die sich auf unveränderlichen Systemen wie Bazzite oder
Silverblue nicht auf dem Host installieren lassen. Das Fenster erscheint
trotzdem normal auf dem Desktop. Der erste Start richtet Container,
Python-Umgebung und npm-Pakete ein und kompiliert die Shell (einige Minuten),
danach startet die App in Sekunden.

Bleibt das Fenster leer, ist meist der DMA-BUF-Renderer von WebKitGTK
schuld; das Skript schaltet ihn deshalb standardmäßig ab
(`WEBKIT_DISABLE_DMABUF_RENDERER=1`).

## Downloads & eigene Plugins

Die Download-Seite listet bereits ausgestrahlte fehlende Folgen und
Wunschlisten-Animes. Links werden an einen Download-Client übergeben, der in
den Download-Ordner der App lädt; dort erkennt und sortiert die App die
Dateien wie gewohnt. Wichtig: Läuft der Client in einem Container oder auf
einem anderen Rechner, muss er in denselben Ordner speichern, den die App als
Download-Ordner kennt. Den Pfad aus Sicht des Clients trägst du in dessen
Einstellungen ein.

Drei Arten von Plugin-Klassen (Schnittstelle: `core/app/downloads/base.py`):

- **`DownloadClient`** nimmt Links entgegen und meldet optional den
  Fortschritt. Eingebaut: qBittorrent (Web-UI-API), Transmission (RPC) und
  JDownloader 2 — über MyJDownloader (empfohlen, z. B. für JDownloader im
  Container) oder über die Erweiterung „Folder Watch“.
- **`SearchSource`** findet Links zu einer Folge oder Serie, wahlweise
  zweistufig: erst die Serie suchen, dann die Varianten pro Folge (Sprache,
  Format, Größe, Hoster).
- **`LinkResolver`** macht aus einem Zwischen-Link (z. B. einem Kurz-Link)
  den eigentlichen Link, bevor er an den Client geht. Ergebnisse, deren Link
  ein Auflöser übernimmt, lassen sich direkt senden statt im Browser zu
  öffnen.

Eigene Plugins: eine `.py`-Datei pro Plugin in den Ordner `plugins` im
App-Datenverzeichnis legen (mit Server: in dessen `data/plugins`) und unter
*Einstellungen → Download-Plugins* auf **Neu laden** klicken. Dort steht
auch, welche Plugins gefunden wurden und warum eine Datei nicht geladen
werden konnte. Die Einstellungen, die
ein Plugin in `settings_schema` angibt, erscheinen automatisch als Formular
auf der Download-Seite. Kommentierte Vorlagen in `core/plugin_examples/`:

- `website_template.py` — Such-Quelle für eine Webseite; nur Adresse und
  CSS-Pfade eintragen. Findet die Suche nichts, versucht sie es ohne „OVA“
  und ähnliche Zusätze und zuletzt mit dem ersten Wort des Titels. Links
  über Zwischenseiten (URL-Shortener) öffnet die App im Browser; den
  endgültigen Link fügt man selbst ein.
- `example_link_list.py` — Such-Quelle, die Links aus einer Textdatei liest.
- `example_link_file_client.py` — Client, der Links in eine Datei schreibt.
- `link_resolver_template.py` — Link-Auflöser, der den Weiterleitungen von
  Kurz-Links (bit.ly, t.co, …) folgt; Vorlage für eigene Auflöser.

In der installierten Windows-Version können Plugins nur Bibliotheken nutzen,
die in der App enthalten sind (u. a. `httpx` und `beautifulsoup4`).

## Linux: AppImage

Ein AppImage ist eine einzelne Datei, die ohne Installation auf praktisch
jeder Distribution läuft – auch auf unveränderlichen Systemen wie Bazzite:

```bash
chmod +x AnimeWatcherPlus_*.AppImage
./AnimeWatcherPlus_*.AppImage
```

Meldet das System, dass FUSE fehlt, startet es auch so:
`./AnimeWatcherPlus_*.AppImage --appimage-extract-and-run`.

Selbst bauen (im selben Distrobox-Container wie `dev_start.sh`):

```bash
./build_linux.sh
```

Ergebnis unter `shell/src-tauri/target/release/bundle/appimage/`. Ein lokal
gebautes AppImage läuft auf Systemen, die mindestens so neu sind wie der
Container (Fedora 44); das AppImage aus den GitHub Releases wird auf Ubuntu
22.04 gebaut und läuft auch auf älteren Systemen.

## Server-Modus (Docker, z. B. auf dem NAS)

Ausführlich, mit allen Schritten: [docs/EINRICHTUNG.md](docs/EINRICHTUNG.md).

Die Bibliothek kann statt in der Desktop-App auf einem Server liegen – dort,
wo die Anime-Dateien sind. Desktop-Apps und die Android-App verbinden sich
dann mit diesem Server; Einstellungen und Download-Plugins liegen zentral
dort, der Scanner läuft dort.

1. `deploy/docker-compose.yml` anpassen (LAN-IP des Servers, Medienordner)
   und starten: `docker compose up -d`. Der Ordner `./data` muss dem
   Container-Benutzer (1000:1000) gehören.
2. Port **8784** ist die API, Port **8785** nur zum Koppeln von Geräten.
   Beide nur ins Heimnetz freigeben; aus dem Internet geht nur 8784 über
   den Reverse Proxy (Vorlage für SWAG: `deploy/swag/`).
3. Beim ersten Start steht ein **Einrichtungscode** im Log
   (`docker logs animewatcherplus`).
4. In der Desktop-App unter *Einstellungen → Datenquelle → Mit Server
   verbinden* die Server-Adresse und den Code eingeben – dieses Gerät wird
   Admin. Danach lässt sich die lokale Bibliothek auf den Server übertragen
   (mit Pfad-Zuordnung, z. B. `Z:\Anime` → `/media/Anime`) und umschalten.

### Sicherheit

- **Keine Passwörter:** Jedes Gerät hat einen eigenen Schlüssel (Ed25519)
  und meldet sich damit an. Der private Teil bleibt auf dem Gerät – im
  Schlüsselbund des Systems bzw. auf Android versiegelt mit einem Schlüssel
  aus dem Android Keystore (StrongBox, wo vorhanden).
- **Koppeln nur im Heimnetz:** mit dem Einrichtungscode (erstes Gerät,
  wird Admin) oder einem 5-Minuten-Code, den ein Admin-Gerät unter
  *Einstellungen → Geräte* erzeugt, plus dessen Freigabe. Ein widerrufenes
  Gerät verliert sofort den Zugriff.
- **Verschlüsselt auch im Heimnetz:** Der Server erzeugt beim ersten Start
  ein eigenes Zertifikat (`data/tls/`). Die Geräte merken es sich beim
  Koppeln; der Code selbst wird dabei nie übertragen, nur ein Nachweis,
  der an genau dieses Zertifikat gebunden ist – wer sich im Netz
  dazwischenschaltet, fällt auf. Aus dem Internet gilt das normale
  Zertifikat des Reverse Proxys.
- Wird `data/tls/` gelöscht, entsteht ein neues Zertifikat und alle Geräte
  müssen neu gekoppelt werden.
- Der Container läuft ohne Zusatzrechte und mit schreibgeschütztem System
  (siehe `deploy/docker-compose.yml`).

## Android-App

Die Android-App zeigt die Bibliothek eines AnimeWatcherPlus-Servers (eine
eigene lokale Bibliothek hat sie nicht). Die APK liegt den GitHub Releases
bei.

- **Koppeln:** im WLAN des Servers den QR-Code scannen, den ein Admin-Gerät
  unter *Einstellungen → Geräte → Gerät hinzufügen* zeigt (oder Adresse und
  Code eintippen), dann am Admin-Gerät freigeben. Unterwegs verbindet sich
  die App über die Internet-Adresse, falls eingetragen.
- **Teilen → Wunschliste:** einen Beitrag (z. B. auf X) über *Teilen* an
  AnimeWatcherPlus schicken. Der Server holt den Text des Beitrags und
  schlägt die darin erkannten Animes zum Hinzufügen vor.

Selbst bauen (im Distrobox-Container; die Toolchain landet in `~/Android`):

```bash
./build_android.sh --setup     # einmalig, ~5 GB
./build_android.sh             # Debug-APK
./build_android.sh --release   # Release-APK (Signierung siehe Skriptkopf)
```

## Release erstellen

Releases baut GitHub automatisch (`.github/workflows/release.yml`): den
Windows-Installer und das Linux-AppImage, beide signiert für den
Auto-Updater, zusammen mit der `latest.json`; dazu die Android-APK und das
Server-Image (`ghcr.io/<owner>/animewatcherplus-server`).

Für die APK zusätzlich den Android-Signierschlüssel hinterlegen
(`ANDROID_KEYSTORE_BASE64` = `base64 -w0 awp-release.jks`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`); ohne ihn wird die APK
übersprungen. Den Schlüssel gut aufbewahren – Updates müssen mit demselben
Schlüssel signiert sein.

Einmalig: den Updater-Signierschlüssel erzeugen (bleibt außerhalb des Repos,
z. B. in `~/.awp-secrets/`) und auf GitHub unter *Settings → Secrets and
variables → Actions* hinterlegen – den **Inhalt** der Schlüsseldatei als
`TAURI_SIGNING_PRIVATE_KEY`, das Passwort als
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`:

```bash
cd shell
npx tauri signer generate -w ~/.awp-secrets/awp-updater.key -p '<Passwort>' --ci
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.awp-secrets/awp-updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD   # fragt nach dem Passwort
```

Der öffentliche Schlüssel (`awp-updater.key.pub`) steht in `tauri.conf.json`
(`plugins.updater.pubkey`) und muss dazu passen. Den privaten Schlüssel gut
sichern: Apps, die mit diesem öffentlichen Schlüssel gebaut wurden, nehmen
nur damit signierte Updates an.

Lokal signiert bauen (z. B. das AppImage): `TAURI_SIGNING_PRIVATE_KEY` (Pfad
oder Inhalt) und `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` setzen, dann
`./build_linux.sh`.

Für die APK zusätzlich den Android-Signierschlüssel hinterlegen
(`ANDROID_KEYSTORE_BASE64` = `base64 -w0 awp-release.jks`,
`ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`); ohne ihn wird die APK
übersprungen. Den Schlüssel gut aufbewahren – Updates müssen mit demselben
Schlüssel signiert sein.

Für jeden Release:

1. Version in `tauri.conf.json`, `Cargo.toml`, `core/pyproject.toml`,
   `core/app/__init__.py` und `shell/ui/package.json` anheben.
2. Auf `main` einen Tag setzen und pushen:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. Der Workflow legt einen **Entwurf** unter *Releases* an. Prüfen und
   veröffentlichen – erst dann bieten installierte Apps das Update an.
4. Nur beim allerersten Release: das Server-Image unter *GitHub → Profil →
   Packages → animewatcherplus-server → Package settings* auf **Public**
   stellen, sonst kann `docker compose pull` es nicht laden.

### Windows-Installer von Hand bauen

Falls nötig, geht es auch lokal unter Windows:

```bash
cd core
.venv\Scripts\python.exe -m pip install -e ".[build]"
.venv\Scripts\python.exe -m PyInstaller core.spec --distpath ..\shell\src-tauri\binaries --noconfirm
move /y ..\shell\src-tauri\binaries\core.exe ..\shell\src-tauri\binaries\core-x86_64-pc-windows-msvc.exe
cd ..\shell\ui
npm run build
cd ..
set TAURI_SIGNING_PRIVATE_KEY=<Pfad zu awp-updater.key>
set TAURI_SIGNING_PRIVATE_KEY_PASSWORD=<Passwort>
set CI=true
cargo tauri build
```

`CI=true` ist nötig, weil `cargo tauri build` beim Signieren sonst interaktiv
nach einem Passwort fragt und hängen bleibt (auch bei einem Schlüssel ohne
Passwort). Ergebnis unter `shell/src-tauri/target/release/bundle/nsis/`.
`shell/src-tauri/binaries/` wird nie committet.

## Bekannte Einschränkungen

- Kein Code-Signing-Zertifikat (Authenticode): Windows SmartScreen warnt bei
  der Erstinstallation und bei Updates. Das lässt sich nur mit einem
  kostenpflichtigen Zertifikat vermeiden.
- Specials, Credits und Trailer (bei AniDB `S1`, `C1`, …) werden beim
  Sortieren und bei fehlenden Folgen nicht berücksichtigt; Dateien heißen
  immer `S01`, da AniDB jede Staffel als eigenen Anime führt.
