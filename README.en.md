<p align="center">
  <img src="./logo_text.jpeg" alt="AnimeWatcher Plus" width="600">
</p>

<p align="center"><a href="./README.md">Deutsche Version</a></p>

# AnimeWatcherPlus

Local desktop application for managing an anime collection.

## Features (current state)

- **Folder management & scanner:** manage content/download folders through
  the UI, startup scan with a diff cache (skips unchanged files) + live
  watch (watchdog) with debounce for ongoing downloads/copy operations.
- **Identification:** `tvshow.nfo` takes priority → local AniDB title dump
  (FTS5 + rapidfuzz) → AniDB HTTP API with rate limiting/backoff and ban
  detection (the ban survives app restarts, a UI banner shows the remaining
  time) → uncertain matches land in the review queue instead of a silent
  misassignment. Duplicate detection when the same AniDB ID exists in two
  folders (FA-29).
- **Artwork & metadata:** poster download into the anime folder,
  `tvshow.nfo` (Jellyfin-compatible), plus an extended `aniinfo.json` with
  all raw AniDB data (tags + weight, expected/local episode count, etc.).
- **Library UI:** virtualized grid, full-text search/filters (year, type,
  tag), detail view with clickable tags, unidentified/review list with
  manual AniDB ID assignment (changeable later too), open the folder
  directly in the file explorer.
- **Settings:** configurable rule for how long after the last episode aired
  automatic metadata rescanning stops being attempted (default 6 months,
  can be disabled globally), plus a manual rescan per series or for the
  whole library that ignores this rule.
- **Structured logging:** rotating JSON log file (`logs/core.log`, 10 MB × 5
  files) in addition to console output — for attaching to bug reports,
  regardless of whether the console happened to be visible.
- **Installer & auto-update:** signed NSIS installer; the app checks GitHub
  Releases on startup and offers updates with one click (see
  [Building the installer](#building-the-installer-release)).

Open milestones from the technical concept: missing episodes (M5), language
analysis (M6), rule engine/auto-sort (M7), download framework (M8),
MAL/TMDB providers (M9).

## Project structure

```
core/       Python/FastAPI backend (sidecar)
shell/      Tauri shell (Rust supervisor) + React frontend (shell/ui)
```

## Prerequisites

- Python 3.12+
- Node.js 20+
- Rust/Cargo + Tauri CLI (`cargo install tauri-cli`) — only for the desktop shell

## Set up & run the backend

```bash
cd core
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on Linux
pip install -e ".[dev]"
python -m uvicorn app.main:app --port 8000
```

Migrations (`alembic upgrade head`) run automatically on startup. App data
lives under `%APPDATA%/AnimeWatcherPlus` or `~/.local/share/AnimeWatcherPlus`.

Tests: `python -m pytest` · Lint: `python -m ruff check app tests`

## Set up & run the frontend (browser dev mode)

```bash
cd shell/ui
npm install
npm run dev
```

Expects the core to be running at `http://127.0.0.1:8000` by default (see
`.env`). Tests: `npm run test` · Type-check: `npx tsc -b`

## Desktop shell (Tauri)

```bash
cd shell
cargo tauri dev
```

The Rust supervisor generates a session token, starts the core from
`core/.venv` on a free port, and polls `/health` before the window opens.
The frontend fetches the port/token via the `get_connection_info` command.
This is only the dev workflow — see below for an installable build.

## Linux: start script

```bash
./dev_start.sh            # desktop app (Tauri window)
./dev_start.sh --browser  # core + UI in the browser only, no Tauri
./dev_start.sh --setup    # set up/compile only, don't start
```

The counterpart to `dev_start.bat`. Everything runs inside a Distrobox
container (`awp-dev`, Fedora 44), since Tauri on Linux needs WebKitGTK/GTK
development packages that immutable systems such as Bazzite or Silverblue
can't install on the host. The window still appears on the normal desktop.
The first run sets up the container, the Python environment and the npm
packages and compiles the shell (a few minutes); after that the app starts in
seconds. The only prerequisite is `distrobox`.

If the window stays blank, WebKitGTK's DMA-BUF renderer is the usual cause;
the script therefore disables it by default
(`WEBKIT_DISABLE_DMABUF_RENDERER=1`).

## Downloads & custom plugins

The download page lists aired missing episodes and wishlist anime. Links are
handed to a download client that downloads into the app's download folder,
where the app detects and sorts the files as usual.

Two kinds of plugin classes (`core/app/downloads/base.py`):

- **`DownloadClient`** receives links. Built in: qBittorrent (Web UI API),
  Transmission (RPC, e.g. in a container) and
  JDownloader 2 – via MyJDownloader (recommended, e.g. for JDownloader in a
  Docker container) or via its "Folder Watch" extension.
- **`SearchSource`** finds links for an episode or a series.

Custom plugins: put one `.py` file per plugin into the `plugins` folder in
the app's data directory and restart the app. Two working, commented
templates are in `core/plugin_examples/`.
For websites there is `HtmlSiteSource`: copy the template
`core/plugin_examples/vorlage_webseite.py` and fill in only the address and
CSS selectors (search → pick series → variants per episode with
language/format/size/hoster). Links through intermediate pages (URL
shorteners) are opened in the browser; the final link is pasted by hand. The settings a plugin declares in
`settings_schema` show up as a form on the download page automatically.

## Building the installer (release)

One-time setup: generate the updater signing key (stays outside the repo,
never committed):

```bash
cargo tauri signer generate -w "%USERPROFILE%\.awp-secrets\awp-updater.key" --ci
```

Then, for every release, the following three steps (core, frontend and
shell are independent — if, say, only the backend changed, it's enough to
re-run step 1 before `cargo tauri build` in step 3 packages everything
into a new installer again):

**1. Build the Python core into a onefile exe with PyInstaller** (onefile,
because Alembic needs its migration scripts as real files at runtime):

```bash
cd core
.venv\Scripts\python.exe -m PyInstaller core.spec --distpath ..\shell\src-tauri\binaries --noconfirm
move /y ..\shell\src-tauri\binaries\core.exe ..\shell\src-tauri\binaries\core-x86_64-pc-windows-msvc.exe
```

`shell/src-tauri/binaries/` is never committed (see `.gitignore`).

**2. Build the frontend:**

```bash
cd shell/ui
npm run build
```

**3. Build the signed NSIS installer:**

```bash
cd shell
set TAURI_SIGNING_PRIVATE_KEY=%USERPROFILE%\.awp-secrets\awp-updater.key
set CI=true
cargo tauri build
```

`CI=true` is required because `cargo tauri build` otherwise tries to
interactively prompt for the key's password while signing and hangs in a
non-interactive shell (a known Tauri quirk, even for a key generated
without a password) — `CI=true` skips that.

The result lands under `shell/src-tauri/target/release/bundle/nsis/`: the
`.exe` installer and its matching `.exe.sig` signature file.

Uploading the release to GitHub is a manual step (no `gh` CLI assumed on
this machine): upload the `.exe` installer, the `.exe.sig` file, and a
`latest.json` (version, notes, `pub_date`,
`platforms.windows-x86_64.signature`/`.url`) as release assets under
`github.com/LinkDarkshire/AnimeWatcherPlus/releases/new`. The installed app
automatically checks `releases/latest/download/latest.json` on startup and
offers an update with one click (signed, silent install, restart).

## Known gaps in this state

- No CI build/release (lint + test only) — the installer build only runs
  locally, manually (see [Building the installer](#building-the-installer-release)).
- No code-signing certificate (Authenticode): Windows SmartScreen warns on
  first install and on every auto-update; this is independent of the
  updater's signing key and can only be avoided with a paid certificate.
