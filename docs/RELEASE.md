# Release erstellen – Kurzanleitung

Gebaut wird alles automatisch auf GitHub (`.github/workflows/release.yml`):
Windows-Installer, Linux-AppImage, Android-APK und das Server-Image. Selbst zu
tun sind nur drei Dinge: Version anheben, Tag setzen, Entwurf veröffentlichen.

Beispiel: Version **0.3.3**.

## 1. Version anheben (Branch + Pull Request)

```bash
cd ~/GitHub/AnimeWatcherPlus
git switch main && git pull
git switch -c release-0.3.3
```

Die Versionsnummer muss an **fünf Stellen** gleich sein:

| Datei | Zeile |
|---|---|
| `core/app/__init__.py` | `__version__ = "0.3.3"` |
| `core/pyproject.toml` | `version = "0.3.3"` |
| `shell/src-tauri/tauri.conf.json` | `"version": "0.3.3"` |
| `shell/src-tauri/Cargo.toml` | `version = "0.3.3"` (unter `[package]`) |
| `shell/ui/package.json` | `"version": "0.3.3"` |

Lock-Dateien nachziehen:

```bash
npm --prefix shell/ui install --package-lock-only
distrobox enter awp-dev -- bash -c 'cd shell/src-tauri && cargo update -p app'
```

Im README (und `README.en.md`) einen Abschnitt **„Neu in 0.3.3“** über dem
vorigen anlegen – der Text dient später auch als Release-Beschreibung.

```bash
git commit -am "Version 0.3.3"
git push -u origin release-0.3.3
gh pr create --fill --base main
```

CI abwarten (`gh pr checks --watch`), dann mergen (`gh pr merge --merge` oder
im Browser).

## 2. Tag setzen – startet den Build

```bash
git switch main && git pull
git tag v0.3.3
git push origin v0.3.3
```

- Der Tag muss auf dem **gemergten** Stand sitzen (also nach dem Merge).
- Der Tag-Name muss zur Versionsnummer in den Dateien passen (`v` + Version).

## 3. Build abwarten (~25 Minuten)

`gh run watch` oder auf GitHub unter *Actions → Release*. Vier Jobs:
Windows, Linux (AppImage), Android (APK) und `server-image`
(`ghcr.io/linkdarkshire/animewatcherplus-server:0.3.3` und `:latest`).

## 4. Veröffentlichen

*Releases* → Entwurf „AnimeWatcherPlus v0.3.3“ → *Edit* → Text aus „Neu in
0.3.3“ einfügen → **Publish release**. Erst danach finden die Apps das Update.

## 5. Server aktualisieren

Auf dem NAS:

```bash
cd ~/animewatcherplus
docker compose pull && docker compose up -d
```

Die Desktop-Apps aktualisieren sich beim nächsten Verbinden auf genau diese
Version; die Android-App bietet die passende APK an.

---

## Reihenfolge und Stolperfallen

- **Erst veröffentlichen, dann den Server aktualisieren.** Sonst suchen die
  Apps nach einem Update, das es öffentlich noch nicht gibt.
- **Tag auf dem falschen Stand** (z. B. vor dem Merge): baut die alte Version
  noch einmal. Tag löschen (`git push origin :refs/tags/v0.3.3 && git tag -d
  v0.3.3`), überzähligen Entwurf unter *Releases* löschen, neu taggen.
- **Signierschlüssel** liegen als GitHub-Secrets
  (`TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]`, `ANDROID_KEYSTORE_*`) und lokal in
  `~/.awp-secrets/`. Diesen Ordner sichern – mit einem neuen Schlüssel nehmen
  installierte Apps keine Updates mehr an.
- **Selbst gebaute Apps** (`build_linux.sh`, `build_android.sh`) sind nur
  dann mit dem Release-Schlüssel signiert, wenn die Schlüssel beim Bauen
  gesetzt sind (`set -a; source ~/.awp-secrets/updater-signing.env; set +a`).
