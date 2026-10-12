#!/usr/bin/env bash
# Builds the Linux AppImage locally: bundles the Python core with PyInstaller,
# builds the UI and packs everything into one AppImage with Tauri.
#
#   ./build_linux.sh
#
# Runs inside the same Distrobox container as dev_start.sh (set up on first
# use). Note: an AppImage runs on systems with the same or a newer glibc than
# the one it was built on -- this container is Fedora 44, so the result runs
# on current distributions (Bazzite, Fedora, Arch, ...). The release workflow
# on GitHub builds on Ubuntu 22.04 for older systems too.
#
# Updater signature: set TAURI_SIGNING_PRIVATE_KEY (path or key content) to
# get the .sig file the auto-updater needs; without it the AppImage is built
# unsigned, which is fine for local use.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER="awp-dev"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

if [[ ! -f /run/.containerenv && ! -f /.dockerenv ]]; then
    "$ROOT/dev_start.sh" --deps  # creates the container on first use
    exec distrobox enter "$CONTAINER" -- "$ROOT/build_linux.sh" "$@"
fi

"$ROOT/dev_start.sh" --deps

log "Baue den Python-Core mit PyInstaller ..."
VENV="$ROOT/core/.venv"
"$VENV/bin/pip" install --quiet -e "$ROOT/core[build]"
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
BINARIES="$ROOT/shell/src-tauri/binaries"
(cd "$ROOT/core" && "$VENV/bin/pyinstaller" core.spec --distpath "$BINARIES" --workpath "$ROOT/core/build" --noconfirm --log-level WARN)
mv -f "$BINARIES/core" "$BINARIES/core-$TRIPLE"

log "Baue das AppImage (dauert beim ersten Mal einige Minuten) ..."
cd "$ROOT/shell"
EXTRA_CONFIG=()
if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    log "Kein TAURI_SIGNING_PRIVATE_KEY gesetzt -- ohne Updater-Signatur."
    EXTRA_CONFIG=(--config '{"bundle":{"createUpdaterArtifacts":false}}')
fi
# linuxdeploy (used by the AppImage bundler) is itself an AppImage; there's
# no FUSE inside the container, so it unpacks itself instead. NO_STRIP: its
# bundled strip is too old for binaries built by a current toolchain.
APPIMAGE_EXTRACT_AND_RUN=1 NO_STRIP=true \
    npx --yes @tauri-apps/cli@2 build --bundles appimage "${EXTRA_CONFIG[@]}"

log "Fertig:"
ls -1 "$ROOT"/shell/src-tauri/target/release/bundle/appimage/*.AppImage
