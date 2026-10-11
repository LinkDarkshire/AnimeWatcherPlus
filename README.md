<p align="center">
  <img src="./logo_text.jpeg" alt="AnimeWatcher Plus" width="600">
</p>

<p align="center"><a href="./README.en.md">English version</a></p>

# AnimeWatcherPlus

Lokale Desktop-Anwendung zur Verwaltung einer Anime-Sammlung: erkennt Animes
in deinen Ordnern über AniDB, zeigt fehlende Folgen, sortiert und benennt
Downloads einheitlich und übergibt neue Folgen an deinen Download-Client.

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
  Start auf neue Versionen in den GitHub Releases.

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
- Linux-Startskript (`dev_start.sh`)
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

Zwei Arten von Plugin-Klassen (Schnittstelle: `core/app/downloads/base.py`):

- **`DownloadClient`** nimmt Links entgegen und meldet optional den
  Fortschritt. Eingebaut: qBittorrent (Web-UI-API), Transmission (RPC) und
  JDownloader 2 — über MyJDownloader (empfohlen, z. B. für JDownloader im
  Container) oder über die Erweiterung „Folder Watch“.
- **`SearchSource`** findet Links zu einer Folge oder Serie, wahlweise
  zweistufig: erst die Serie suchen, dann die Varianten pro Folge (Sprache,
  Format, Größe, Hoster).

Eigene Plugins: eine `.py`-Datei pro Plugin in den Ordner `plugins` im
App-Datenverzeichnis legen und die App neu starten. Die Einstellungen, die
ein Plugin in `settings_schema` angibt, erscheinen automatisch als Formular
auf der Download-Seite. Kommentierte Vorlagen in `core/plugin_examples/`:

- `website_template.py` — Such-Quelle für eine Webseite; nur Adresse und
  CSS-Pfade eintragen. Findet die Suche nichts, versucht sie es ohne „OVA“
  und ähnliche Zusätze und zuletzt mit dem ersten Wort des Titels. Links
  über Zwischenseiten (URL-Shortener) öffnet die App im Browser; den
  endgültigen Link fügt man selbst ein.
- `example_link_list.py` — Such-Quelle, die Links aus einer Textdatei liest.
- `example_link_file_client.py` — Client, der Links in eine Datei schreibt.

In der installierten Windows-Version können Plugins nur Bibliotheken nutzen,
die in der App enthalten sind (u. a. `httpx` und `beautifulsoup4`).

## Installer bauen (Release)

Einmalig: Updater-Signierschlüssel erzeugen (bleibt außerhalb des Repos, wird
nie committet):

```bash
cargo tauri signer generate -w "%USERPROFILE%\.awp-secrets\awp-updater.key" --ci
```

Danach für jeden Release die folgenden drei Schritte. Core, Frontend und Shell
sind unabhängig — hat sich z. B. nur das Backend geändert, reicht es, Schritt 1
erneut auszuführen, bevor Schritt 3 alles zu einem neuen Installer packt.

**1. Python-Core mit PyInstaller zu einer einzelnen Exe bauen** (eine Datei,
weil die Datenbank-Migrationen zur Laufzeit als echte Dateien gebraucht
werden):

```bash
cd core
.venv\Scripts\python.exe -m PyInstaller core.spec --distpath ..\shell\src-tauri\binaries --noconfirm
move /y ..\shell\src-tauri\binaries\core.exe ..\shell\src-tauri\binaries\core-x86_64-pc-windows-msvc.exe
```

`shell/src-tauri/binaries/` wird nie committet (siehe `.gitignore`).

**2. Frontend bauen:**

```bash
cd shell/ui
npm run build
```

**3. Signierten NSIS-Installer bauen:**

```bash
cd shell
set TAURI_SIGNING_PRIVATE_KEY=%USERPROFILE%\.awp-secrets\awp-updater.key
set CI=true
cargo tauri build
```

`CI=true` ist nötig, weil `cargo tauri build` beim Signieren sonst interaktiv
nach einem Passwort fragt und in einer nicht-interaktiven Shell hängen bleibt
(auch bei einem Schlüssel ohne Passwort).

Ergebnis unter `shell/src-tauri/target/release/bundle/nsis/`: der
`.exe`-Installer und die zugehörige `.exe.sig`-Signatur.

Release auf GitHub: den Installer, die `.exe.sig` und eine `latest.json`
(Version, Notes, `pub_date`, `platforms.windows-x86_64.signature`/`.url`) als
Release-Assets unter `github.com/LinkDarkshire/AnimeWatcherPlus/releases/new`
hochladen. Die installierte App prüft `releases/latest/download/latest.json`
beim Start und bietet das Update per Klick an. Die Version muss in
`tauri.conf.json`, `Cargo.toml`, `core/pyproject.toml`, `core/app/main.py` und
`shell/ui/package.json` übereinstimmen.

## Bekannte Einschränkungen

- Der Installer wird nur lokal gebaut; die CI prüft Lint, Typen und Tests.
- Kein Code-Signing-Zertifikat (Authenticode): Windows SmartScreen warnt bei
  der Erstinstallation und bei Updates. Das lässt sich nur mit einem
  kostenpflichtigen Zertifikat vermeiden.
- Specials, Credits und Trailer (bei AniDB `S1`, `C1`, …) werden beim
  Sortieren und bei fehlenden Folgen nicht berücksichtigt; Dateien heißen
  immer `S01`, da AniDB jede Staffel als eigenen Anime führt.
