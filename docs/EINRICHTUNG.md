# AnimeWatcherPlus einrichten – von null an

Diese Anleitung führt Schritt für Schritt durch die Einrichtung. Es gibt zwei
Varianten:

| | **A: Nur Desktop** | **B: Server + Geräte** |
|---|---|---|
| Bibliothek liegt … | auf dem PC | auf dem Server (z. B. NAS) |
| Geeignet, wenn … | die Animes auf dem PC oder einem eingebundenen Laufwerk liegen | die Animes auf einem NAS liegen und mehrere Geräte zugreifen sollen |
| Android-App | – | ja |
| Zugriff von unterwegs | – | optional, über einen Reverse Proxy |

Variante A ist in zehn Minuten erledigt. Variante B braucht Docker auf dem
Server und etwas mehr Zeit. Von A nach B (und zurück) lässt sich jederzeit
wechseln, ohne etwas zu verlieren.

---

## Inhalt

1. [Variante A: Nur Desktop](#1-variante-a-nur-desktop)
2. [Variante B: Server auf dem NAS](#2-variante-b-server-auf-dem-nas)
3. [Desktop mit dem Server verbinden](#3-desktop-mit-dem-server-verbinden)
4. [Android-App](#4-android-app)
5. [Zugriff von unterwegs (optional)](#5-zugriff-von-unterwegs-optional)
6. [Weitere Geräte, Geräte entfernen](#6-weitere-geräte-geräte-entfernen)
7. [Downloads einrichten (optional)](#7-downloads-einrichten-optional)
8. [Updates und Sicherung](#8-updates-und-sicherung)
9. [Fehlerbehebung](#9-fehlerbehebung)

---

## 1. Variante A: Nur Desktop

### 1.1 Installieren

Die aktuelle Version gibt es unter
[Releases](https://github.com/LinkDarkshire/AnimeWatcherPlus/releases/latest).

- **Windows:** `AnimeWatcherPlus_<Version>_x64-setup.exe` herunterladen und
  ausführen. Meldet Windows SmartScreen „Unbekannter Herausgeber“, auf
  *Weitere Informationen → Trotzdem ausführen* klicken.
- **Linux:** `AnimeWatcherPlus_<Version>_amd64.AppImage` herunterladen, dann:
  ```bash
  chmod +x AnimeWatcherPlus_*.AppImage
  ./AnimeWatcherPlus_*.AppImage
  ```
  Fehlt FUSE: `./AnimeWatcherPlus_*.AppImage --appimage-extract-and-run`.

Die App aktualisiert sich ab jetzt selbst: Beim Start fragt sie nach, wenn
eine neue Version da ist.

### 1.2 Ordner hinzufügen

Unter **Mehr → Ordner** (am Desktop oben: *Ordner*):

1. **Inhalts-Ordner**: der Ordner, in dem die Animes liegen – je Anime ein
   Unterordner, z. B. `D:\Anime\Cowboy Bebop\…`. Typ *Content*.
2. **Download-Ordner** (optional): wohin neue Folgen heruntergeladen werden.
   Die App erkennt sie dort und sortiert sie in die Bibliothek ein. Typ
   *Download*.

Danach scannt die App die Ordner und erkennt die Animes über die Titelliste
von AniDB. Das dauert beim ersten Mal eine Weile: AniDB erlaubt nur eine
Anfrage alle paar Sekunden, die Anzeige oben rechts zeigt den Fortschritt.

> **Hinweis zu AniDB:** Zu viele Anfragen führen zu einer vorübergehenden
> Sperre. Die App hält sich an die Grenzen und setzt nach einer Sperre
> selbst wieder ein – einfach laufen lassen.

### 1.3 Durchsehen

- **Abfragen:** Animes, die nicht eindeutig erkannt wurden, Dateien zum
  Einsortieren oder Umbenennen. Hier einmal durchgehen.
- **Fehlend:** Folgen, die laut AniDB existieren, aber fehlen.
- **Einstellungen:** Sprache, Titel-Reihenfolge, ob Einsortieren und
  Umbenennen automatisch passieren oder erst nachfragen.

Fertig. Wer später doch einen Server möchte: weiter mit Abschnitt 2 – die
vorhandene Bibliothek lässt sich mitnehmen.

---

## 2. Variante B: Server auf dem NAS

Der Server ist ein Docker-Container. Er läuft dort, wo die Anime-Dateien
liegen, scannt sie und hält die Bibliothek, Einstellungen und
Download-Plugins für alle Geräte.

### 2.1 Was du brauchst

- Ein NAS oder einen Rechner mit **Docker** und **Docker Compose**
  (Synology: *Container Manager*, Unraid/TrueNAS/OpenMediaVault: Docker-
  bzw. Compose-Unterstützung, Linux: `docker` + `docker compose`).
- Eine **feste IP-Adresse** des Servers im Heimnetz (im Router als feste
  Zuweisung eintragen), im Folgenden `192.168.1.10`.
- Den Pfad zu deinen Animes auf dem Server, im Folgenden
  `/volume1/media/Anime`.
- Die Benutzer- und Gruppen-ID, der die Anime-Dateien gehören. Auf dem
  Server per SSH:
  ```bash
  ls -ln /volume1/media/Anime | head -3   # 3. und 4. Spalte: UID und GID
  id -u; id -g                             # die eigenen IDs
  ```
  Im Folgenden `1000:1000`.

### 2.2 Ordner anlegen

Per SSH auf dem Server (oder im Dateimanager des NAS):

```bash
mkdir -p ~/animewatcherplus/data
cd ~/animewatcherplus
sudo chown 1000:1000 data     # dieselben IDs wie oben
```

> Wichtig: `data` muss **vorher** existieren und dem Benutzer gehören, sonst
> legt Docker ihn als `root` an und der Server kann nicht schreiben.

### 2.3 docker-compose.yml

Im Ordner `~/animewatcherplus` eine Datei `docker-compose.yml` anlegen. Die
Vorlage liegt im Repository unter
[`deploy/docker-compose.yml`](../deploy/docker-compose.yml). Ohne Zugriff von
unterwegs (Abschnitt 5) reicht diese Fassung:

```yaml
services:
  animewatcherplus:
    image: ghcr.io/linkdarkshire/animewatcherplus-server:latest
    container_name: animewatcherplus
    user: "1000:1000"                         # UID:GID aus 2.1
    environment:
      - TZ=Europe/Berlin
      - AWP_SERVER_NAME=AnimeWatcherPlus      # Name, den die Geräte anzeigen
    volumes:
      - ./data:/data                          # Datenbank, Zertifikat, Plugins
      - /volume1/media/Anime:/media/Anime     # deine Animes
      # - /volume1/media/Downloads:/media/Downloads   # optional: Download-Ordner
    ports:
      - "192.168.1.10:8784:8784"              # App-Zugriff (Heimnetz)
      - "192.168.1.10:8785:8785"              # Koppeln neuer Geräte (nur Heimnetz)
    restart: unless-stopped
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp
```

Anpassen:

- `user`: die IDs aus 2.1 – der Server muss die Dateien verschieben und
  umbenennen dürfen.
- `volumes`: links der Pfad auf dem Server, rechts der Pfad, unter dem der
  Server ihn sieht. In der App gibst du später die **rechten** Pfade an
  (`/media/Anime`).
- `ports`: die IP des Servers. So sind beide Ports nur im Heimnetz
  erreichbar. **Im Router keinen der beiden Ports freigeben.**

### 2.4 Starten

```bash
cd ~/animewatcherplus
docker compose up -d
docker logs animewatcherplus
```

Im Log steht beim ersten Start ein Kasten:

```
============================================================
  AnimeWatcherPlus server -- first-time setup
  Setup code: ABCD-EFGH-JKLM
  ...
  Server certificate: bd0615282da32218...
============================================================
```

Den **Einrichtungscode** brauchst du gleich. Er gilt, bis das erste Gerät
gekoppelt ist; nach einem Neustart des Containers gibt es einen neuen.

Beim ersten Start lädt der Server außerdem einmal die AniDB-Titelliste.

> Der Server erzeugt beim ersten Start ein eigenes Zertifikat (`data/tls/`).
> Darüber ist auch der Verkehr im Heimnetz verschlüsselt. Die Geräte merken
> sich das Zertifikat beim Koppeln.

---

## 3. Desktop mit dem Server verbinden

### 3.1 Koppeln (erstes Gerät = Admin)

1. Desktop-App installieren (1.1) und starten. Der PC muss im **selben
   Heimnetz** wie der Server sein.
2. **Einstellungen → Datenquelle → Mit Server verbinden…**
3. Adresse des Servers eingeben: `192.168.1.10` → *Suchen*.
4. Gerätename (z. B. „Desktop“) und den **Einrichtungscode** aus 2.4
   eingeben → *Koppeln*.

Das Gerät ist jetzt **Admin**: Es darf weitere Geräte hinzufügen und die
Bibliothek übertragen.

### 3.2 Bibliothek übertragen oder neu anfangen

**Du hast schon eine Bibliothek in der Desktop-App** (Variante A):

1. **Einstellungen → Datenquelle → Bibliothek auf den Server übertragen…**
2. Für jeden Ordner angeben, unter welchem Pfad **der Server** ihn sieht,
   z. B. `Z:\Anime` → `/media/Anime` oder `/mnt/nas/Anime` → `/media/Anime`.
   Leer lassen heißt unverändert.
3. *Übertragen*. Übertragen werden Bibliothek, Einstellungen,
   Download-Plugins und der AniDB-Zwischenspeicher – die Dateien selbst
   bleiben, wo sie sind.
4. Danach *Zum Server wechseln* – die App startet neu und zeigt die
   Bibliothek vom Server.

**Du fängst neu an:**

1. **Einstellungen → Datenquelle → Zum Server wechseln** (die App startet
   neu).
2. **Ordner** hinzufügen, jetzt mit den Pfaden aus Sicht des Servers:
   `/media/Anime` (Typ *Content*), ggf. `/media/Downloads` (Typ
   *Download*).

### 3.3 Zurück zur lokalen Bibliothek

**Einstellungen → Datenquelle → Zurück zur lokalen Bibliothek…** Auf Wunsch
nimmt die App die Bibliothek vom Server mit (dann wieder Pfade zuordnen, nur
im Heimnetz). Die bisherige lokale Datenbank bleibt als Sicherung erhalten.

---

## 4. Android-App

### 4.1 Installieren

1. Auf dem Handy `AnimeWatcherPlus_<Version>_android.apk` von den
   [Releases](https://github.com/LinkDarkshire/AnimeWatcherPlus/releases/latest)
   herunterladen.
2. Öffnen. Android fragt einmalig, ob der Browser bzw. Dateimanager Apps
   installieren darf – erlauben (*Unbekannte Apps installieren*).
3. Installieren.

### 4.2 Koppeln

Das Handy muss dafür im **WLAN des Servers** sein.

1. Am **Desktop** (Admin): **Einstellungen → Geräte → Gerät hinzufügen**. Es
   erscheinen ein QR-Code und ein Code, 5 Minuten gültig.
2. Auf dem **Handy** die App öffnen → **QR-Code scannen** und den Code am
   Bildschirm scannen (Kamera-Zugriff erlauben). Alternativ Adresse und Code
   eintippen.
3. Gerätenamen prüfen → **Koppeln**.
4. Das Handy zeigt einen **Fingerabdruck**, z. B. `7235-5381-99ED`. Am
   Desktop erscheint die Anfrage mit demselben Fingerabdruck. Nur wenn beide
   übereinstimmen: **Freigeben** (optional „Als Admin-Gerät“).
5. Auf dem Handy *Zur Bibliothek*.

### 4.3 Beiträge teilen → Wunschliste

Einen Beitrag, etwa auf X, über **Teilen → AnimeWatcherPlus** an die App
schicken. Die App öffnet die Wunschliste und schlägt die Animes vor, die im
Beitrag erkannt wurden – mit *Hinzufügen* übernehmen. Wird nichts erkannt,
unten selbst nach dem Titel suchen.

---

## 5. Zugriff von unterwegs (optional)

Unterwegs verbinden sich die Apps über einen **Reverse Proxy** mit gültigem
Zertifikat. Zu Hause gehen sie weiterhin direkt zum Server; die App wählt
das automatisch.

Freigegeben wird **nur Port 8784, und nur über den Reverse Proxy**. Port 8785
(Koppeln) bleibt immer im Heimnetz.

### 5.1 Mit SWAG (linuxserver.io)

Voraussetzung: SWAG läuft bereits mit deiner Domain.

1. **Subdomain:** `animewatcherplus.deinedomain.de` beim DNS-Anbieter
   anlegen (bzw. als CNAME), und im SWAG-Container zu den Zertifikats-
   Subdomains hinzufügen (`SUBDOMAINS=…,animewatcherplus` bzw. Wildcard).
2. **Netzwerk:** den AnimeWatcherPlus-Container ins Netzwerk von SWAG
   hängen. In der `docker-compose.yml` ergänzen (Name des Netzwerks mit
   `docker network ls` nachsehen):
   ```yaml
       networks:
         - swag

   networks:
     swag:
       external: true
   ```
   Dann `docker compose up -d`.
3. **Proxy-Konfiguration:**
   [`deploy/swag/animewatcherplus.subdomain.conf`](../deploy/swag/animewatcherplus.subdomain.conf)
   nach `/config/nginx/proxy-confs/` von SWAG kopieren und SWAG neu starten
   (`docker restart swag`).
4. Test im Browser: `https://animewatcherplus.deinedomain.de/health` zeigt
   `{"status":"ok"}`.
5. In der App: **Einstellungen → Datenquelle → Adresse aus dem Internet**:
   `https://animewatcherplus.deinedomain.de` → *Speichern*. Auf jedem
   Gerät einmal eintragen.

### 5.2 Mit einem anderen Reverse Proxy

Wichtig sind drei Dinge:

- Weiterleitung an `https://<server>:8784` – der Container spricht selbst
  HTTPS mit eigenem Zertifikat; der Proxy darf es nicht prüfen (nginx tut
  das standardmäßig nicht, Caddy: `tls_insecure_skip_verify`).
- WebSockets durchreichen (Pfad `/ws`).
- Nie Port 8785 und nie die Pfade `/pair` und `/admin` weiterleiten (der
  Server liefert sie auf 8784 ohnehin nicht aus).

---

## 6. Weitere Geräte, Geräte entfernen

- **Weiterer PC:** Desktop-App installieren → *Einstellungen → Datenquelle →
  Mit Server verbinden* → Adresse → den **Kopplungscode** eingeben, den ein
  Admin-Gerät unter *Einstellungen → Geräte → Gerät hinzufügen* zeigt →
  Fingerabdruck vergleichen und am Admin-Gerät freigeben. Danach *Zum
  Server wechseln*.
- **Gerät verloren oder verkauft:** an einem Admin-Gerät unter
  *Einstellungen → Geräte* **Widerrufen**. Es verliert sofort den Zugriff.
- **Gerät abmelden:** am Gerät selbst *Einstellungen → Datenquelle →
  Kopplung entfernen* (und am Admin-Gerät widerrufen).

Es gibt keine Passwörter. Jedes Gerät hat einen eigenen Schlüssel, der das
Gerät nie verlässt (Schlüsselbund des Systems, auf Android im Hardware-
Keystore).

---

## 7. Downloads einrichten (optional)

Unter **Downloads → Einrichtung: Clients & Quellen** einen Download-Client
eintragen: qBittorrent, Transmission oder JDownloader (über MyJDownloader).

Wichtig: Der Client muss in den **Download-Ordner** der App speichern. Läuft
der Client auf einem anderen Gerät oder in einem anderen Container, trägst
du dort den Pfad aus seiner Sicht ein – gemeint ist aber derselbe Ordner.
Mehr dazu und zu eigenen Such-Plugins im
[README](../README.md#downloads--eigene-plugins).

---

## 8. Updates und Sicherung

### Updates

- **Desktop:** automatisch – beim Start meldet die App neue Versionen.
- **Server:**
  ```bash
  cd ~/animewatcherplus
  docker compose pull && docker compose up -d
  ```
  Desktop und Server sollten dieselbe Version haben.
- **Android:** neue APK aus den Releases über die alte installieren.

### Sicherung

Alles Wichtige liegt im Datenordner – einfach den ganzen Ordner sichern:

| | Ort |
|---|---|
| Server | `~/animewatcherplus/data` |
| Desktop (Windows) | `%APPDATA%\AnimeWatcherPlus` |
| Desktop (Linux) | `~/.local/share/AnimeWatcherPlus` |

Darin: `library.db` (Bibliothek und Einstellungen), `plugins/`,
`cache/` und auf dem Server `tls/` (das Zertifikat). Geht `tls/` verloren,
erzeugt der Server ein neues, und **alle Geräte müssen neu gekoppelt
werden**.

---

## 9. Fehlerbehebung

**„Unter … antwortet kein AnimeWatcherPlus-Server“ beim Koppeln**
- Ist das Gerät im selben Heimnetz (nicht im Gast-WLAN, kein VPN aktiv)?
- Stimmt die IP? Läuft der Container (`docker ps`)?
- Ist Port 8785 auf der richtigen IP freigegeben (`ports:` in der
  Compose-Datei) und blockiert keine Firewall auf dem NAS?

**„Einrichtungscode falsch oder abgelaufen“**
Nach fünf Fehlversuchen oder einem Neustart des Containers ist der Code
ungültig. `docker restart animewatcherplus`, dann den neuen Code aus
`docker logs animewatcherplus` nehmen.

**„Server nicht erreichbar“ (roter Hinweis oben)**
Zu Hause: Server prüfen. Unterwegs: Ist eine Internet-Adresse eingetragen
(5.1, Schritt 5) und funktioniert sie im Browser (`…/health`)?

**„Dieses Gerät ist auf dem Server nicht mehr freigegeben“**
Das Gerät wurde widerrufen oder der Server neu aufgesetzt. *Neu koppeln*
antippen und Abschnitt 4.2 bzw. 6 folgen (im Heimnetz).

**„Das Zertifikat des Servers hat sich geändert“**
Der Server hat ein neues Zertifikat (z. B. weil `data/tls/` gelöscht wurde).
War das nicht so geplant, Server prüfen. Sonst das Gerät neu koppeln.

**„Das Zertifikat des Servers passt nicht zum QR-Code“**
Zwischen Handy und Server antwortet ein anderes Gerät. Nicht koppeln – das
Netzwerk prüfen (öffentliches WLAN? anderer Router?).

**Server startet nicht / „Permission denied“ in den Logs**
`data` gehört nicht dem Benutzer aus `user:` → `sudo chown -R 1000:1000
data`. Bei den Anime-Ordnern muss derselbe Benutzer lesen und schreiben
dürfen.

**Animes werden nicht erkannt**
In der Anzeige oben rechts nachsehen, ob AniDB gerade gesperrt hat – dann
wartet die App. Sonst unter *Abfragen* von Hand zuordnen (AniDB-ID).

---

## Für Entwickler

Aus dem Quellcode starten und bauen (Windows, Linux, Android) sowie
Releases veröffentlichen: siehe [README](../README.md).
