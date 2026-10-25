<p align="center">
  <img src="./logo_text.jpeg" alt="AnimeWatcher Plus" width="600">
</p>

<p align="center"><a href="./README.md">Deutsche Version</a></p>

# AnimeWatcherPlus

A local desktop app for managing an anime collection: it identifies the anime
in your folders via AniDB, shows missing episodes, sorts and renames downloads
consistently and hands new episodes to your download client. The library
can also live on a server (e.g. a NAS), shared by several PCs and the
Android app.

**Step-by-step setup (German):** [docs/EINRICHTUNG.md](docs/EINRICHTUNG.md)

## Features

- **Folders & scanner:** manage content and download folders in the app. A
  scan at startup that skips unchanged files, then live watching. Changes are
  only processed once a download or copy has finished. Network drives that
  become reachable later are picked up automatically.
- **Identification via AniDB:** an existing `tvshow.nfo` first, otherwise the
  folder name is matched against the local AniDB title list (refreshed every
  7 days). Uncertain matches go to the review queue instead of being guessed.
  AniDB requests are rate limited, cached for 7 days and respect bans; after
  a ban the app resumes the identifications that were left over.
- **AniDB indicator:** the header shows live what is being looked up on
  AniDB, how many jobs are waiting, and until when a ban or the daily limit
  applies.
- **Artwork & metadata:** poster, `tvshow.nfo` and episode NFOs in the
  Jellyfin/Kodi format plus an `aniinfo.json` with all AniDB data in the
  anime's folder. Titles in English, romanized or Japanese -- configurable
  separately for display and for folder names.
- **Library:** paginated grid (25/50/100 per page), full-text search, filters
  for status, tag and missing episodes, a detail page with episodes, manual
  episode numbers and an open-folder button.
- **Missing episodes:** AniDB's episode list compared with the files on disk,
  per series and as an overview.
- **Sorting & renaming:** move anime from download folders into a content
  folder (into an existing series or as a new one) and name folders and
  files consistently (`Title/Title - S01E05 - Episode name.mkv`). Subtitles
  and other companion files move along. On request or automatically.
- **Duplicates:** the same series in two folders is detected and shown for a
  decision.
- **Wishlist:** search the AniDB title list for anime you don't have yet and
  keep them on a list. They don't appear in the library until they turn up
  in one of your folders.
- **Downloads:** hand missing episodes and wishes to a download client, with
  live progress. Built in: qBittorrent, Transmission and JDownloader 2 (via
  MyJDownloader or Folder Watch). Search sources and more clients can be
  added as plugins (see below).
- **Maintenance:** a repair scan that restores titles, episode numbers and
  metadata from local data, without asking AniDB.
- **Logging:** a rotating JSON log file (`logs/core.log`, 10 MB × 5 files) to
  attach to bug reports.
- **Installer & auto-update:** a signed NSIS installer; the app checks GitHub
  Releases for new versions at startup. On Linux as an AppImage that runs
  without installation.

## New in 0.3.4

- **Linux: no more freezes from emoji.** The WebKit in the AppImage crashed
  on certain color emoji (e.g. flags) and the app froze; the affected font
  (COLRv1) is hidden from the app's window, emoji show in Twemoji or
  monochrome instead.
- **Sending with a link resolver doesn't wait:** "send" answers at once;
  "Active downloads" shows "resolving link", then the progress or why it
  failed (at most 2 minutes for the whole chain).
- **Several tags at once** in the library filter (anime with all of them).
- **Version info** under Settings → Version (app and server).

## New in 0.3.3

- **Plugins can no longer freeze the server:** every download plugin call
  (search, send, progress, link resolving, …) runs isolated with a time
  limit; a plugin that blocks or hangs only costs its own result.
- **AppImage:** "open in browser" and "open folder" work reliably (browser
  and file manager start without the AppImage's environment).

## New in 0.3.2

- **Link resolvers (new in 0.3.2):** a new plugin kind next to download
  clients and search sources. A resolver turns an intermediate link (e.g. a
  short link) into the final one before it goes to the download client;
  results that would otherwise need the browser can be sent directly.
  Template: `core/plugin_examples/link_resolver_template.py` (follows the
  redirects of bit.ly, t.co & co.).
- **Updates through the server:** with a server, updating the server is
  enough – desktop apps install exactly its version when they connect,
  Android offers the matching APK.
- **Downloads:** "hide finished" also removes finished downloads from
  JDownloader/qBittorrent/Transmission (files stay); a finished download
  triggers a rescan of the download folder.
- **Plugins:** overview in Settings with load errors, reload without restart.
- Open server folders via an SMB share (per-device mapping).
- New app icon; on Linux the binary is `animewatcherplus` instead of `app`.
- Fixed: the local core kept running after the app restarted.

(0.3.1 was not released; everything since 0.3.0 is listed here.)

## New in 0.3.0

- **Server mode:** the library as a Docker container on the NAS, where the
  files are; desktop apps connect to it, settings and plugins are shared.
  Switch between local and server data and move the library both ways.
- **Android app:** library, wishlist and downloads from the server on the
  phone; pairing by QR code; share a post (e.g. from X) to get wishlist
  suggestions.
- **Security without passwords:** per-device keys, pairing only in the home
  network with an admin device's approval, encrypted LAN traffic with a
  pinned server certificate.
- Phone- and tablet-sized UI (bottom navigation).
- New update signing key: self-built versions before 0.3.0 need 0.3.0
  installed by hand once; after that the app updates itself again.

## Server mode and Android app

- Server: `deploy/docker-compose.yml` (Docker), first start prints a setup
  code (`docker logs animewatcherplus`); pair the desktop app under
  *Settings → Data source*. Port 8784 is the API (LAN; from the internet
  only through a reverse proxy, template in `deploy/swag/`), port 8785 is
  for pairing and must stay in the LAN.
- Android: the APK is attached to each release; pair it by scanning the QR
  code an admin device shows under *Settings → Devices → Add device*.
  Build it yourself with `./build_android.sh --setup` (once) and
  `./build_android.sh`.
- Full walkthrough: [docs/EINRICHTUNG.md](docs/EINRICHTUNG.md).

## New in 0.2.0

- Wishlist, download page with plugins for clients and search sources, live
  download progress
- qBittorrent, Transmission and MyJDownloader support
- AniDB activity indicator and automatic resume after a ban
- Paginated library instead of endless scrolling, with a configurable page size
- Sorting/renaming takes subtitles and companion files along and no longer
  deletes files that weren't moved
- The "empty folder" prompt only appears for folders that really are empty
- Failed actions are shown as a message
- Linux: AppImage (`build_linux.sh`) and start script (`dev_start.sh`)
- Releases for Windows and Linux are built automatically on GitHub
- Many fixes (title search, offline folders, memory leaks, desktop shell
  security)

## Project structure

```
core/       Python/FastAPI backend ("core", runs as a sidecar process)
shell/      Tauri desktop shell (Rust) + React UI (shell/ui)
```

## Prerequisites

- Python 3.12+
- Node.js 20+
- Rust/Cargo + Tauri CLI (`cargo install tauri-cli`) — only for the desktop shell

On Linux, `distrobox` is all you need, see [Linux](#linux-start-script).

## Set up & run the backend

```bash
cd core
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on Linux
pip install -e ".[dev]"
python -m uvicorn app.main:app --port 8000
```

Database migrations run automatically at startup. App data lives in
`%APPDATA%/AnimeWatcherPlus` or `~/.local/share/AnimeWatcherPlus`.

Tests: `python -m pytest` · Lint: `ruff check app tests` · Types: `mypy app --ignore-missing-imports`

## Set up & run the frontend (browser mode)

```bash
cd shell/ui
npm install
npm run dev
```

Expects the core at `http://127.0.0.1:8000` (see `.env`).
Tests: `npm run test` · Type-check: `npx tsc -b` · Lint: `npm run lint`

## Desktop shell (Tauri)

```bash
cd shell
cargo tauri dev
```

or simply `dev_start.bat` on Windows. The shell creates a token per session,
starts the core from `core/.venv` on a free port and opens the window once it
answers. This is the development mode -- see below for an installable build.

## Linux start script

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
seconds.

If the window stays blank, WebKitGTK's DMA-BUF renderer is the usual cause;
the script therefore disables it by default
(`WEBKIT_DISABLE_DMABUF_RENDERER=1`).

## Downloads & custom plugins

The download page lists aired missing episodes and wishlist anime. Links are
handed to a download client that downloads into the app's download folder,
where the app detects and sorts the files as usual. Important: if the client
runs in a container or on another machine, it has to save into the same
folder the app knows as its download folder; enter the path as the client
sees it in the client's settings.

Two kinds of plugin classes (interface: `core/app/downloads/base.py`):

- **`DownloadClient`** receives links and can report progress. Built in:
  qBittorrent (Web UI API), Transmission (RPC) and JDownloader 2 -- via
  MyJDownloader (recommended, e.g. for JDownloader in a container) or via its
  "Folder Watch" extension.
- **`SearchSource`** finds links for an episode or a series, optionally in two
  steps: find the series first, then the variants per episode (language,
  format, size, hoster).

Custom plugins: put one `.py` file per plugin into the `plugins` folder in the
app's data directory and restart the app. The settings a plugin declares in
`settings_schema` show up as a form on the download page automatically.
Annotated templates in `core/plugin_examples/`:

- `website_template.py` -- a search source for a website; fill in only the
  address and CSS selectors. If the search finds nothing, it retries without
  "OVA" and similar words, and finally with the title's first word. Links
  through intermediate pages (URL shorteners) are opened in the browser; the
  final link is pasted by hand.
- `example_link_list.py` -- a search source that reads links from a text file.
- `example_link_file_client.py` -- a client that writes links to a file.

In the installed Windows version, plugins can only use libraries that ship
with the app (including `httpx` and `beautifulsoup4`).

## Linux: AppImage

An AppImage is a single file that runs without installation on practically
any distribution -- including immutable systems such as Bazzite:

```bash
chmod +x AnimeWatcherPlus_*.AppImage
./AnimeWatcherPlus_*.AppImage
```

If the system reports that FUSE is missing, this works too:
`./AnimeWatcherPlus_*.AppImage --appimage-extract-and-run`.

To build it yourself (in the same Distrobox container as `dev_start.sh`):

```bash
./build_linux.sh
```

The result is in `shell/src-tauri/target/release/bundle/appimage/`. A locally
built AppImage runs on systems at least as new as the container (Fedora 44);
the AppImage from the GitHub releases is built on Ubuntu 22.04 and runs on
older systems too.

## Creating a release

GitHub builds releases automatically (`.github/workflows/release.yml`): the
Windows installer and the Linux AppImage, both signed for the auto-updater,
together with `latest.json`.

Once: create the updater signing key (it stays outside the repo) and store its
**content** on GitHub under *Settings → Secrets and variables → Actions* as
`TAURI_SIGNING_PRIVATE_KEY` (plus `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` if the
key has a password):

```bash
cargo tauri signer generate -w "%USERPROFILE%\.awp-secrets\awp-updater.key" --ci
```

The public key is in `tauri.conf.json` (`plugins.updater.pubkey`) and has to
match it.

For every release:

1. Raise the version in `tauri.conf.json`, `Cargo.toml`, `core/pyproject.toml`,
   `core/app/__init__.py` and `shell/ui/package.json`.
2. Tag `main` and push the tag:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. The workflow creates a **draft** under *Releases*. Check it and publish
   it -- only then do installed apps offer the update.

### Building the Windows installer by hand

If needed, it also works locally on Windows:

```bash
cd core
.venv\Scripts\python.exe -m pip install -e ".[build]"
.venv\Scripts\python.exe -m PyInstaller core.spec --distpath ..\shell\src-tauri\binaries --noconfirm
move /y ..\shell\src-tauri\binaries\core.exe ..\shell\src-tauri\binaries\core-x86_64-pc-windows-msvc.exe
cd ..\shell\ui
npm run build
cd ..
set TAURI_SIGNING_PRIVATE_KEY=%USERPROFILE%\.awp-secrets\awp-updater.key
set CI=true
cargo tauri build
```

`CI=true` is needed because `cargo tauri build` otherwise asks for the key's
password interactively while signing and hangs (even for a key without a
password). The result is in `shell/src-tauri/target/release/bundle/nsis/`.
`shell/src-tauri/binaries/` is never committed.

## Known limitations

- No code-signing certificate (Authenticode): Windows SmartScreen warns on the
  first install and on updates. Only a paid certificate avoids that.
- Specials, credits and trailers (AniDB `S1`, `C1`, ...) are left out of
  sorting and missing episodes; files are always named `S01`, since AniDB
  lists every season as its own anime.
