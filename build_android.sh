#!/usr/bin/env bash
# Builds the Android app (APK). The phone app has no library of its own: it
# connects to an AnimeWatcherPlus server (see deploy/).
#
#   ./build_android.sh --setup     Install the Android toolchain into ~/Android (once, ~5 GB)
#   ./build_android.sh             Debug APK (installable right away, e.g. `adb install`)
#   ./build_android.sh --release   Release APK, signed if a keystore is configured (below)
#
# Everything goes into ~/Android -- JDK 17, Android SDK + NDK and a separate
# rustup with the Android targets -- so the system and its Rust stay untouched.
#
# Release signing: set ANDROID_KEYSTORE (path to the .jks), ANDROID_KEY_ALIAS
# and ANDROID_KEYSTORE_PASSWORD. Make a keystore once with
#   ~/Android/jdk-17/bin/keytool -genkey -v -keystore awp-release.jks \
#       -keyalg RSA -keysize 4096 -validity 10000 -alias awp
# and keep it safe: updates must be signed with the same key.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER="awp-dev"
ANDROID_DIR="$HOME/Android"
NDK_VERSION="29.0.14206865"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

if [[ ! -f /run/.containerenv && ! -f /.dockerenv ]]; then
    "$ROOT/dev_start.sh" --deps  # creates the container on first use
    exec distrobox enter "$CONTAINER" -- "$ROOT/build_android.sh" "$@"
fi

setup() {
    mkdir -p "$ANDROID_DIR/Sdk/cmdline-tools" "$ANDROID_DIR/dl"
    cd "$ANDROID_DIR/dl"
    if [[ ! -x "$ANDROID_DIR/jdk-17/bin/java" ]]; then
        log "Lade JDK 17 (Temurin) ..."
        curl -fsSL -o jdk17.tar.gz "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse"
        mkdir -p "$ANDROID_DIR/jdk-17" && tar -xzf jdk17.tar.gz -C "$ANDROID_DIR/jdk-17" --strip-components=1
    fi
    if [[ ! -x "$ANDROID_DIR/Sdk/cmdline-tools/latest/bin/sdkmanager" ]]; then
        log "Lade die Android-Kommandozeilen-Tools ..."
        curl -fsSL -o cmdline.zip "https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip"
        rm -rf ct && python3 -c "import zipfile; zipfile.ZipFile('cmdline.zip').extractall('ct')"
        mv ct/cmdline-tools "$ANDROID_DIR/Sdk/cmdline-tools/latest"
        chmod +x "$ANDROID_DIR/Sdk/cmdline-tools/latest/bin/"*
    fi
    export JAVA_HOME="$ANDROID_DIR/jdk-17" ANDROID_HOME="$ANDROID_DIR/Sdk"
    log "Installiere SDK-Pakete und NDK (das dauert) ..."
    yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null
    "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --install \
        "platform-tools" "platforms;android-36" "build-tools;35.0.0" "ndk;$NDK_VERSION" >/dev/null
    if [[ ! -x "$ANDROID_DIR/cargo/bin/rustup" ]]; then
        log "Installiere rustup mit den Android-Zielen ..."
        curl -fsSL https://sh.rustup.rs -o rustup-init.sh
        CARGO_HOME="$ANDROID_DIR/cargo" RUSTUP_HOME="$ANDROID_DIR/rustup" \
            sh rustup-init.sh -y --no-modify-path --profile minimal --default-toolchain stable >/dev/null
    fi
    CARGO_HOME="$ANDROID_DIR/cargo" RUSTUP_HOME="$ANDROID_DIR/rustup" "$ANDROID_DIR/cargo/bin/rustup" target add \
        aarch64-linux-android armv7-linux-androideabi x86_64-linux-android i686-linux-android >/dev/null
    log "Fertig. Jetzt: ./build_android.sh"
}

if [[ "${1:-}" == "--setup" ]]; then
    setup
    exit 0
fi

if [[ ! -x "$ANDROID_DIR/cargo/bin/rustup" || ! -d "$ANDROID_DIR/Sdk/ndk/$NDK_VERSION" ]]; then
    echo "Android-Toolchain fehlt -- einmalig ./build_android.sh --setup ausführen." >&2
    exit 1
fi
export JAVA_HOME="$ANDROID_DIR/jdk-17"
export ANDROID_HOME="$ANDROID_DIR/Sdk"
export NDK_HOME="$ANDROID_DIR/Sdk/ndk/$NDK_VERSION"
export CARGO_HOME="$ANDROID_DIR/cargo"
export RUSTUP_HOME="$ANDROID_DIR/rustup"
export PATH="$ANDROID_DIR/cargo/bin:$JAVA_HOME/bin:$PATH"

cd "$ROOT/shell"
npm install --silent
npm --prefix ui install --silent

if [[ "${1:-}" == "--release" ]]; then
    KEYSTORE_PROPERTIES="$ROOT/shell/src-tauri/gen/android/keystore.properties"
    if [[ -n "${ANDROID_KEYSTORE:-}" ]]; then
        printf 'storeFile=%s\npassword=%s\nkeyAlias=%s\n' \
            "$ANDROID_KEYSTORE" "${ANDROID_KEYSTORE_PASSWORD:?}" "${ANDROID_KEY_ALIAS:?}" > "$KEYSTORE_PROPERTIES"
    else
        log "Kein ANDROID_KEYSTORE gesetzt -- die Release-APK bleibt unsigniert (nicht installierbar)."
        rm -f "$KEYSTORE_PROPERTIES"
    fi
    log "Baue die Release-APK ..."
    npm run tauri -- android build --apk --target aarch64 armv7
    ls -1 "$ROOT"/shell/src-tauri/gen/android/app/build/outputs/apk/universal/release/*.apk
else
    log "Baue die Debug-APK ..."
    npm run tauri -- android build --apk --debug --target aarch64 armv7 x86_64
    ls -1 "$ROOT"/shell/src-tauri/gen/android/app/build/outputs/apk/universal/debug/*.apk
fi
