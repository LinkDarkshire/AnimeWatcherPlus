"""Vorlage: Such-Quelle für eine Webseite -- nur Adresse und CSS-Pfade eintragen.

So geht's:
  1. Diese Datei in den Plugin-Ordner der App kopieren und umbenennen
     (z. B. meine_seite.py). Den Ordner zeigt die Download-Seite unter
     "Einrichtung" an.
  2. Unten `id`, `name`, BASE_URL und die CSS-Pfade für deine Seite eintragen.
  3. App neu starten, auf der Download-Seite unter "Einrichtung" die Quelle
     hinzufügen und auf "Testen" klicken.

CSS-Pfade findest du im Browser: Rechtsklick auf das Element -> "Untersuchen",
dann in den Entwicklerwerkzeugen Rechtsklick auf die markierte Zeile ->
"Kopieren" -> "Selektor kopieren". Kürzer und robuster als der kopierte Pfad
ist meist ein Klassenname: aus <article class="result-card dim"> wird
"article.result-card". Leerzeichen bedeutet "irgendwo darunter",
">" bedeutet "direkt darunter".

Alle Pfade außer SERIES_ITEM und EPISODE_ITEM sind RELATIV zum jeweiligen
Element darüber -- also so, wie man die Seite von außen nach innen liest.

Die Werte unten gehören zu einer erfundenen Seite mit diesem Aufbau:

  Suchseite  https://www.beispiel-seite.example/?s=frieren
    <div class="results">
      <article class="result-card">
        <a href="frieren/"><h3>Frieren</h3></a>
      </article>
      ...
    </div>

  Serienseite  https://www.beispiel-seite.example/frieren/
    <div class="episode-list">
      <div class="episode">
        <div class="episode-header">Episode 02</div>
        <div class="episode-body">
          <div class="variant-header">Subbed</div>          <- Variante 1
          <div class="variant-meta">
            <span class="meta-item">Format: MKV</span>
            <span class="meta-item">Size: 350 MB</span>
          </div>
          <div class="variant-actions">
            <a class="download" href="https://mega.nz/...">MEGA</a>
            <a class="stream" href="/watch/2">Stream</a>
          </div>
          <div class="variant-header">RAW</div>             <- Variante 2
          ...
        </div>
      </div>
    </div>
"""

from __future__ import annotations

from app.downloads import HtmlSiteSource


class MeineSeite(HtmlSiteSource):
    # Eindeutige ID (nur Kleinbuchstaben/Unterstriche). Nach dem ersten
    # Einrichten nicht mehr ändern -- gespeicherte Einträge verweisen darauf.
    id = "vorlage_webseite"
    name = "Vorlage Webseite"
    description = "Beispiel-Quelle -- vor der Nutzung Adresse und Pfade anpassen."

    # --- Seite -------------------------------------------------------------
    BASE_URL = "https://www.beispiel-seite.example"
    # Wird an BASE_URL angehängt. {query} = der Suchbegriff (wird automatisch
    # URL-kodiert). Beispiele: "/?s={query}", "/search?q={query}",
    # "/suche/{query}/".
    SEARCH_PATH = "/?s={query}"

    # --- Schritt 1: Suchergebnisse -----------------------------------------------
    # Ein Element pro Treffer (absoluter Pfad ab der ganzen Seite).
    SERIES_ITEM = "div.results article.result-card"
    # Darin: der Name des Treffers.
    SERIES_TITLE = "a h3"
    # Darin: der Link zur Serienseite (das <a>-Element). Relative Links wie
    # "frieren/" werden automatisch zur vollen Adresse ergänzt.
    # Leer lassen (""), wenn SERIES_ITEM selbst schon das <a> ist.
    SERIES_LINK = "a"

    # --- Schritt 2: Serienseite ---------------------------------------------------
    # Ein Element pro Folge (absoluter Pfad ab der ganzen Seite).
    EPISODE_ITEM = "div.episode-list div.episode"
    # Darin: der Folgenname, z. B. "Episode 02".
    EPISODE_LABEL = "div.episode-header"
    # Wie die Folgennummer aus dem Folgennamen gelesen wird: die erste Zahl.
    # Andere Muster: r"Folge\s*(\d+)", r"E(\d+)".
    EPISODE_NUMBER_PATTERN = r"(\d+)"
    # Optional: der Bereich in der Folge, in dem die Varianten stehen.
    # None = die ganze Folge.
    EPISODE_BODY = "div.episode-body"
    # Optional: hier beginnt jeweils eine neue Variante (Sprache, Sub/RAW, ...);
    # ihr Text wird als Name angezeigt. Kopfzeile, Details und Links einer
    # Variante dürfen in einem gemeinsamen Element stecken ODER einfach
    # nacheinander stehen (wie im Beispiel oben) -- beides funktioniert.
    # None = jede Folge hat nur eine Variante.
    VARIANT_HEADER = "div.variant-header"
    # Optional: Detail-Angaben einer Variante (Format, Größe, Untertitel, Audio).
    DETAIL_ITEM = "span.meta-item"
    # Wie ein Detail in Bezeichnung und Wert geteilt wird ("Format: MKV").
    # Steht beides in eigenen Elementen, stattdessen DETAIL_LABEL und
    # DETAIL_VALUE als Pfade (relativ zu DETAIL_ITEM) setzen.
    DETAIL_SEPARATOR = ":"
    DETAIL_LABEL = None
    DETAIL_VALUE = None
    # Download-Links (das <a>-Element). Der Text des Links wird als Hoster
    # angezeigt ("MEGA"); mehrere Links pro Variante sind normal.
    DOWNLOAD_LINK = "div.variant-actions a.download"
    # Optional: Stream-Links. Werden nur angezeigt (im Browser öffnen),
    # nie an einen Download-Client geschickt. None = nicht anzeigen.
    STREAM_LINK = "div.variant-actions a.stream"

    # --- Links mit Zwischenseite ------------------------------------------------
    # Regulärer Ausdruck für Links, die erst über eine Zwischenseite führen
    # (URL-Shortener, Captcha, Werbeseite). Solche Links öffnet die App im
    # Browser; den Link, bei dem du am Ende landest, fügst du dann in das
    # Link-Feld ein. Beispiele: r"ouo\.io|shrinkme" -- oder r".*", wenn alle
    # Links der Seite so funktionieren. None = alle Links direkt verwenden.
    BROWSER_LINK_PATTERN = None

    # Wie viele Titel des Animes nacheinander gesucht werden, bis etwas
    # gefunden wird (englisch, romaji, japanisch, Synonyme).
    MAX_TITLES_TRIED = 3
