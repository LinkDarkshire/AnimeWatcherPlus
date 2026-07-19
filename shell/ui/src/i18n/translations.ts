// Adding a language: add its code to LANGUAGES, then add a matching object
// here satisfying Record<TranslationKey, string> -- TypeScript will flag any
// missing/extra keys against `de` (the canonical key source) immediately.

export const LANGUAGES = {
  de: "Deutsch",
  en: "English",
} as const

export type Language = keyof typeof LANGUAGES

const de = {
  "nav.library": "Bibliothek",
  "nav.review": "Unidentifiziert",
  "nav.folders": "Ordner",
  "nav.settings": "Einstellungen",

  "common.loading": "Lädt…",
  "common.cancel": "Abbrechen",
  "common.save": "Speichern",
  "common.saved": "Gespeichert.",
  "common.rescan": "Rescan",
  "common.apply": "Übernehmen",
  "common.assign": "Zuweisen",

  "animeDetail.notFound": "Anime nicht gefunden.",
  "animeDetail.back": "← Zurück",
  "animeDetail.openFolder": "Ordner öffnen",
  "animeDetail.lastUpdate": "Letztes Update: {date}",
  "animeDetail.lastEpisode": "· Letzte Folge: {date}",
  "animeDetail.stale": "Veraltet — kein Auto-Rescan",
  "animeDetail.duplicatePrefix": "Duplikat — dieselbe AniDB-ID liegt bereits in",
  "animeDetail.anotherFolder": "einem anderen Ordner",
  "animeDetail.changeAnidbId": "AniDB-ID ändern",
  "animeDetail.newAnidbIdPlaceholder": "Neue AniDB-ID",
  "animeDetail.confirmChangeId":
    "AniDB-ID wirklich von {from} auf {to} ändern? Titel, Tags und Episoden werden dabei komplett neu geladen.",
  "animeDetail.change": "Ändern",
  "animeDetail.manualIdentification": "Manuelle Identifikation",
  "animeDetail.candidateInfo": "(AID {aid}, Score {score})",
  "animeDetail.enterAnidbId": "AniDB-ID eingeben",
  "animeDetail.identifyFailed": "Identifikation fehlgeschlagen. AniDB-ID prüfen.",

  "folders.createError": "Fehler beim Anlegen",
  "folders.pathPlaceholder": "Absoluter Pfad, z.B. D:/Anime/Content",
  "folders.typeContent": "Content",
  "folders.typeDownload": "Download",
  "folders.namePlaceholder": "Anzeigename (optional)",
  "folders.add": "Ordner hinzufügen",
  "folders.offline": "Offline",
  "folders.confirmDelete": 'Ordner "{name}" wirklich entfernen?',
  "folders.remove": "Entfernen",

  "library.statusAll": "Alle Status",
  "library.statusIdentified": "Identifiziert",
  "library.statusPending": "In Bearbeitung",
  "library.statusNeedsManualId": "Unidentifiziert",
  "library.statusReview": "Review nötig",
  "library.searchPlaceholder": "Suche nach Titel…",
  "library.allTags": "Alle Tags",
  "library.animeCount": "{count} Animes",
  "library.loadError": "Bibliothek konnte nicht geladen werden.",

  "reviewQueue.title": "Unidentifiziert / Review",
  "reviewQueue.empty": "Nichts zu überprüfen.",
  "reviewQueue.review": "Review",
  "reviewQueue.noId": "Keine ID",
  "reviewQueue.manualIdPlaceholder": "AniDB-ID manuell eingeben",

  "settings.rescanTitle": "Automatischer Metadaten-Rescan",
  "settings.rescanDescription":
    "Beim Start werden alle identifizierten Serien erneut bei AniDB abgefragt (neue Folgen, geänderte Metadaten) — außer solchen, deren letzte bekannte Folge schon länger als die Schwelle unten zurückliegt (wahrscheinlich abgeschlossen oder abgebrochen, es kommt also vermutlich keine neue Folge mehr).",
  "settings.thresholdLabel": "Schwelle (Tage seit letzter Folge):",
  "settings.thresholdMonths": "≈ {months} Monate",
  "settings.ruleEnabledLabel":
    "Regel aktiv (deaktivieren = alle Serien werden beim Start immer automatisch aktualisiert)",
  "settings.fullRescanTitle": "Vollständiger Rescan",
  "settings.fullRescanDescription":
    "Fragt alle identifizierten Serien sofort erneut bei AniDB ab — ignoriert dabei die Regel oben vollständig, auch für bereits als veraltet markierte Serien.",
  "settings.fullRescanButton": "Alle Serien jetzt aktualisieren",
  "settings.fullRescanQueued": "{count} Serien für Rescan eingeplant.",
  "settings.languageTitle": "Sprache",
  "settings.languageDescription": "Sprache der Benutzeroberfläche.",

  "aniDbBan.message": "AniDB hat diese App vorübergehend gesperrt. Identifikation neuer Animes pausiert bis {date}.",

  "animeStatus.identified": "Identifiziert",
  "animeStatus.pending": "Wird verarbeitet…",
  "animeStatus.needsManualId": "Unidentifiziert",
  "animeStatus.review": "Review nötig",

  "animeCard.noArtwork": "Kein Artwork",
  "animeCard.missing": "Nicht gefunden",
  "animeCard.duplicate": "Duplikat",

  "updateBanner.available": "Update auf Version {version} verfügbar.",
  "updateBanner.installButton": "Jetzt installieren & neu starten",
  "updateBanner.downloading": "Update wird heruntergeladen und installiert…",
  "updateBanner.failed": "Update fehlgeschlagen",
  "updateBanner.failedWithMessage": "Update fehlgeschlagen: {message}",
}

export type TranslationKey = keyof typeof de

const en: Record<TranslationKey, string> = {
  "nav.library": "Library",
  "nav.review": "Unidentified",
  "nav.folders": "Folders",
  "nav.settings": "Settings",

  "common.loading": "Loading…",
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.saved": "Saved.",
  "common.rescan": "Rescan",
  "common.apply": "Apply",
  "common.assign": "Assign",

  "animeDetail.notFound": "Anime not found.",
  "animeDetail.back": "← Back",
  "animeDetail.openFolder": "Open folder",
  "animeDetail.lastUpdate": "Last update: {date}",
  "animeDetail.lastEpisode": "· Last episode: {date}",
  "animeDetail.stale": "Stale — no auto-rescan",
  "animeDetail.duplicatePrefix": "Duplicate — the same AniDB ID already exists in",
  "animeDetail.anotherFolder": "another folder",
  "animeDetail.changeAnidbId": "Change AniDB ID",
  "animeDetail.newAnidbIdPlaceholder": "New AniDB ID",
  "animeDetail.confirmChangeId":
    "Really change the AniDB ID from {from} to {to}? Title, tags and episodes will be completely reloaded.",
  "animeDetail.change": "Change",
  "animeDetail.manualIdentification": "Manual identification",
  "animeDetail.candidateInfo": "(AID {aid}, score {score})",
  "animeDetail.enterAnidbId": "Enter AniDB ID",
  "animeDetail.identifyFailed": "Identification failed. Check the AniDB ID.",

  "folders.createError": "Failed to create",
  "folders.pathPlaceholder": "Absolute path, e.g. D:/Anime/Content",
  "folders.typeContent": "Content",
  "folders.typeDownload": "Download",
  "folders.namePlaceholder": "Display name (optional)",
  "folders.add": "Add folder",
  "folders.offline": "Offline",
  "folders.confirmDelete": 'Really remove folder "{name}"?',
  "folders.remove": "Remove",

  "library.statusAll": "All statuses",
  "library.statusIdentified": "Identified",
  "library.statusPending": "Processing",
  "library.statusNeedsManualId": "Unidentified",
  "library.statusReview": "Needs review",
  "library.searchPlaceholder": "Search by title…",
  "library.allTags": "All tags",
  "library.animeCount": "{count} anime",
  "library.loadError": "Failed to load the library.",

  "reviewQueue.title": "Unidentified / Review",
  "reviewQueue.empty": "Nothing to review.",
  "reviewQueue.review": "Review",
  "reviewQueue.noId": "No ID",
  "reviewQueue.manualIdPlaceholder": "Enter AniDB ID manually",

  "settings.rescanTitle": "Automatic metadata rescan",
  "settings.rescanDescription":
    "On startup, all identified series are checked against AniDB again (new episodes, changed metadata) — except ones whose last known episode aired longer ago than the threshold below (likely finished or dropped, so a new episode probably isn't coming).",
  "settings.thresholdLabel": "Threshold (days since last episode):",
  "settings.thresholdMonths": "≈ {months} months",
  "settings.ruleEnabledLabel": "Rule active (disable = all series are always auto-updated on startup)",
  "settings.fullRescanTitle": "Full rescan",
  "settings.fullRescanDescription":
    "Immediately re-checks all identified series against AniDB — completely ignoring the rule above, even for series already marked stale.",
  "settings.fullRescanButton": "Update all series now",
  "settings.fullRescanQueued": "{count} series queued for rescan.",
  "settings.languageTitle": "Language",
  "settings.languageDescription": "User interface language.",

  "aniDbBan.message": "AniDB has temporarily banned this app. Identification of new anime is paused until {date}.",

  "animeStatus.identified": "Identified",
  "animeStatus.pending": "Processing…",
  "animeStatus.needsManualId": "Unidentified",
  "animeStatus.review": "Needs review",

  "animeCard.noArtwork": "No artwork",
  "animeCard.missing": "Missing",
  "animeCard.duplicate": "Duplicate",

  "updateBanner.available": "Update to version {version} available.",
  "updateBanner.installButton": "Install now & restart",
  "updateBanner.downloading": "Downloading and installing update…",
  "updateBanner.failed": "Update failed",
  "updateBanner.failedWithMessage": "Update failed: {message}",
}

export const translations: Record<Language, Record<TranslationKey, string>> = { de, en }

export function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  )
}
