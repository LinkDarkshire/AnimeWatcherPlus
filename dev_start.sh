#!/usr/bin/env bash
# Linux counterpart to dev_start.bat: starts AnimeWatcherPlus in dev mode
# (Tauri window + Python core, hot reload for the UI).
#
#   ./dev_start.sh            Desktop app (Tauri window)
#   ./dev_start.sh --browser  Core + UI only, opened in the browser
#                             (no Tauri build; "open folder" is unavailable)
#   ./dev_start.sh --setup    Only set up and compile, don't start anything
#   ./dev_start.sh --deps     Only install dependencies (used by build_linux.sh)
#
# Everything runs inside a Distrobox container ("awp-dev", Fedora 44). Tauri
# needs WebKitGTK/GTK development packages, which immutable systems such as
# Bazzite/Silverblue can't install on the host -- the container keeps the
# host untouched while the app window still shows up on the normal desktop.
# The first run creates the container and installs everything (takes a
# while: the Rust build alone is several minutes); later runs start in
# seconds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER="awp-dev"
IMAGE="registry.fedoraproject.org/fedora-toolbox:44"
MODE="${1:-}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

in_container() { [[ -f /run/.containerenv || -f /.dockerenv ]]; }

# --- Host side: hand over to the container -----------------------------------
if ! in_container; then
    command -v distrobox >/dev/null || { echo "distrobox fehlt (auf Bazzite vorinstalliert)." >&2; exit 1; }
    if ! distrobox list --no-color 2>/dev/null | awk -F'|' '{gsub(/ /,"",$2); print $2}' | grep -qx "$CONTAINER"; then
        log "Lege Container '$CONTAINER' an (einmalig) ..."
        distrobox create --yes --name "$CONTAINER" --image "$IMAGE"
    fi
    exec distrobox enter "$CONTAINER" -- "$ROOT/dev_start.sh" "$@"
fi

# --- Container side: one-time system packages --------------------------------
SETUP_MARKER="/etc/awp-dev-setup-v1"
if [[ ! -f "$SETUP_MARKER" ]]; then
    log "Installiere Build-Abhängigkeiten im Container (einmalig) ..."
    sudo dnf install -y \
        webkit2gtk4.1-devel gtk3-devel libsoup3-devel javascriptcoregtk4.1-devel \
        libappindicator-gtk3-devel librsvg2-devel openssl-devel \
        gcc gcc-c++ make pkgconf-pkg-config curl file \
        rust cargo nodejs npm python3 python3-devel
    # "Ordner öffnen" in der App ruft xdg-open auf -- im Container gibt es
    # keinen Dateimanager, also an den Host durchreichen.
    sudo ln -sf /usr/bin/distrobox-host-exec /usr/local/bin/xdg-open
    sudo touch "$SETUP_MARKER"
fi

# --- Python core (core/.venv, the interpreter the Tauri shell launches) ------
VENV="$ROOT/core/.venv"
if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -c "" 2>/dev/null; then
    log "Lege Python-Umgebung core/.venv an ..."
    rm -rf "$VENV"
    python3 -m venv "$VENV"
fi
DEPS_MARKER="$VENV/.awp-deps-installed"
if [[ ! -f "$DEPS_MARKER" || "$ROOT/core/pyproject.toml" -nt "$DEPS_MARKER" ]]; then
    log "Installiere Python-Abhängigkeiten ..."
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -e "$ROOT/core[dev]"
    touch "$DEPS_MARKER"
fi

# --- Frontend dependencies ----------------------------------------------------
UI="$ROOT/shell/ui"
if [[ ! -d "$UI/node_modules" || "$UI/package-lock.json" -nt "$UI/node_modules/.package-lock.json" ]]; then
    log "Installiere Frontend-Abhängigkeiten ..."
    npm --prefix "$UI" ci
fi

if [[ "$MODE" == "--deps" ]]; then
    exit 0
fi

# --- Browser mode: core on :8000 + Vite on :5173, no Tauri --------------------
if [[ "$MODE" == "--browser" ]]; then
    log "Starte Core auf http://127.0.0.1:8000 ..."
    (cd "$ROOT/core" && exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
    CORE_PID=$!
    trap 'kill $CORE_PID 2>/dev/null || true' EXIT
    log "Starte UI auf http://localhost:5173 (Strg+C beendet beides) ..."
    (sleep 3 && xdg-open http://localhost:5173 >/dev/null 2>&1 || true) &
    npm --prefix "$UI" run dev
    exit 0
fi

# --- Desktop mode: Tauri dev --------------------------------------------------
# tauri.conf.json's bundle.externalBin makes every cargo build require the
# sidecar binary for this target to exist, even in dev builds, which launch
# core/.venv's Python instead and never run it. A placeholder is enough
# (same trick as the CI's cargo check); the real one comes from PyInstaller.
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
SIDECAR="$ROOT/shell/src-tauri/binaries/core-$TRIPLE"
if [[ ! -e "$SIDECAR" ]]; then
    mkdir -p "$(dirname "$SIDECAR")"
    printf '#!/bin/sh\necho "Platzhalter -- im Dev-Modus startet die Shell core/.venv" >&2\nexit 1\n' > "$SIDECAR"
    chmod +x "$SIDECAR"
fi

# WebKitGTK's DMA-BUF renderer shows a blank window on many GPU/driver
# combinations (NVIDIA in particular). Off by default here; set it to 0 to
# test with it enabled.
export WEBKIT_DISABLE_DMABUF_RENDERER="${WEBKIT_DISABLE_DMABUF_RENDERER:-1}"

if [[ "$MODE" == "--setup" ]]; then
    log "Kompiliere die Desktop-Shell ..."
    cargo build --manifest-path "$ROOT/shell/src-tauri/Cargo.toml"
    log "Fertig eingerichtet. Starten mit: ./dev_start.sh"
    exit 0
fi

log "Starte AnimeWatcherPlus (Tauri dev) ..."
cd "$ROOT/shell"
# The Tauri CLI via npx instead of `cargo install tauri-cli`: a prebuilt
# binary, no extra multi-minute compile on first run.
exec npx --yes @tauri-apps/cli@2 dev
