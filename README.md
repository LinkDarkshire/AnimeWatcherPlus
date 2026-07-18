<p align="center">
  <img src="./logo_text.jpeg" alt="AnimeWatcher Plus" width="600">
</p>

# AnimeWatcherPlus

Lokale Desktop-Anwendung zur Verwaltung einer Anime-Sammlung.

## Features (aktueller Stand)

- **Ordnerverwaltung & Scanner:** Content-/Download-Ordner über die UI
  verwalten, Startscan mit Diff-Cache (überspringt unveränderte Dateien) +
  Live-Watch (watchdog) mit Debounce für laufende Downloads/Kopiervorgänge.
- **Identifikation:** `tvshow.nfo`-Vorrang → lokaler AniDB-Titeldump
  (FTS5 + rapidfuzz) → AniDB-HTTP-API mit Rate-Limiting/Backoff und
  Ban-Erkennung (Sperre übersteht App-Neustarts, UI-Banner zeigt Restzeit) →
  unsichere Treffer landen in der Review-Queue statt stiller Fehlzuordnung.
  Duplikat-Erkennung, wenn dieselbe AniDB-ID in zwei Ordnern liegt (FA-29).
- **Artwork & Metadaten:** Poster-Download in den Anime-Ordner, `tvshow.nfo`
  (Jellyfin-kompatibel) sowie eine erweiterte `aniinfo.json` mit allen
  AniDB-Rohdaten (Tags + Gewichtung, Episodenzahl erwartet/lokal, u.a.).
- **Bibliotheks-UI:** virtualisiertes Grid, Volltextsuche/Filter (Jahr, Typ,
  Tag), Detailansicht mit klickbaren Tags, Unidentifiziert-/Review-Liste mit
  manueller AniDB-ID-Zuordnung (auch nachträglich änderbar), Ordner direkt im
  Datei-Explorer öffnen.
- **Einstellungen:** konfigurierbare Regel, ab welcher Zeit seit der letzten
  Folge kein automatisches Metadaten-Rescan mehr versucht wird (Default 6
  Monate, global abschaltbar), plus manueller Rescan pro Serie oder für die
  ganze Bibliothek unter Ignorieren dieser Regel.
- **Strukturiertes Logging:** rotierende JSON-Logdatei (`logs/core.log`,
  10 MB × 5 Dateien) zusätzlich zur Konsolenausgabe — zum Beilegen bei
  Problemen, unabhängig davon ob die Konsole gerade sichtbar war.
- **Installer & Auto-Update:** per `build.bat` gebauter, signierter
  NSIS-Installer; die App prüft beim Start gegen GitHub Releases und bietet
  Updates per Klick an (siehe [Installer bauen](#installer-bauen-release)).

Offene Meilensteine aus dem technischen Konzept: fehlende Episoden (M5),
Sprachanalyse (M6), Regel-Engine/Auto-Sort (M7), Download-Framework (M8),
MAL-/TMDB-Provider (M9).

## Projektstruktur

```
core/       Python/FastAPI-Backend (Sidecar)
shell/      Tauri-Shell (Rust-Supervisor) + React-Frontend (shell/ui)
```

## Voraussetzungen

- Python 3.12+
- Node.js 20+
- Rust/Cargo + Tauri-CLI (`cargo install tauri-cli`) — nur für die Desktop-Shell

## Backend einrichten & starten

```bash
cd core
python -m venv .venv
.venv/Scripts/activate   # bzw. source .venv/bin/activate unter Linux
pip install -e ".[dev]"
python -m uvicorn app.main:app --port 8000
```

Migrationen (`alembic upgrade head`) laufen automatisch beim Start. App-Daten
liegen unter `%APPDATA%/AnimeWatcherPlus` bzw. `~/.local/share/animewatcherplus`.

Tests: `python -m pytest` · Lint: `python -m ruff check app tests`

## Frontend einrichten & starten (Browser-Dev-Modus)

```bash
cd shell/ui
npm install
npm run dev
```

Erwartet den Core standardmäßig unter `http://127.0.0.1:8000` (siehe `.env`).
Tests: `npm run test` · Typecheck: `npx tsc -b`

## Desktop-Shell (Tauri)

```bash
cd shell
cargo tauri dev
```

Der Rust-Supervisor generiert ein Sitzungs-Token, startet den Core aus
`core/.venv` auf einem freien Port und pollt `/health`, bevor das Fenster
öffnet. Das Frontend fragt Port/Token per `get_connection_info`-Command ab.
Das ist nur der Dev-Workflow — für einen installierbaren Build siehe unten.

## Installer bauen (Release)

Einmalig: Updater-Signierschlüssel erzeugen (bleibt außerhalb des Repos, wird
nie committet):

```bash
cargo tauri signer generate -w "%USERPROFILE%\.awp-secrets\awp-updater.key" --ci
```

Danach ein einziger Befehl im Repo-Root:

```bash
build.bat
```

Das baut nacheinander: den Python-Core per PyInstaller zu einer
`core-x86_64-pc-windows-msvc.exe` (Onefile, landet in
`shell/src-tauri/binaries/` — dieser Ordner wird nie committet, siehe
`.gitignore`), das Frontend, und zuletzt per `cargo tauri build` einen
signierten NSIS-Installer unter
`shell/src-tauri/target/release/bundle/nsis/`. `build.bat` findet den
Signierschlüssel automatisch am obigen Pfad (überschreibbar per
`TAURI_SIGNING_PRIVATE_KEY`-Env-Var).

Release-Upload zu GitHub ist ein manueller Schritt (kein `gh`-CLI auf dieser
Maschine vorausgesetzt): den `.exe`-Installer, die zugehörige `.exe.sig`-Datei
und eine `latest.json` (Version, Notes, `pub_date`,
`platforms.windows-x86_64.signature`/`.url`) als Release-Assets unter
`github.com/LinkDarkshire/AnimeWatcherPlus/releases/new` hochladen. Die
installierte App prüft `releases/latest/download/latest.json` automatisch
beim Start und bietet ein Update per Klick an (signiert, stille Installation,
Neustart).

**Nur einzelne Komponenten neu bauen:** Core, Frontend und Shell sind
unabhängig — hat sich z.B. nur das Backend geändert, muss vor dem nächsten
Release nur der PyInstaller-Schritt neu laufen, bevor `cargo tauri build`
wieder alles zu einem neuen Installer zusammenpackt.

## Bekannte Lücken in diesem Stand

- Kein CI-Build/Release (nur Lint+Test) — der Installer-Build läuft nur lokal
  per `build.bat`.
- Kein Code-Signing-Zertifikat (Authenticode): Windows SmartScreen warnt bei
  Erst-Install und bei jedem Auto-Update, das ist unabhängig vom
  Updater-Signierschlüssel und nur mit einem kostenpflichtigen Zertifikat
  vermeidbar.
