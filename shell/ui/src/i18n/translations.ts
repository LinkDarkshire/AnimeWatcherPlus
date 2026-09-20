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
  "nav.missingEpisodes": "Fehlende Folgen",
  "nav.review": "Abfragen",
  "nav.folders": "Ordner",
  "nav.settings": "Einstellungen",

  "common.loading": "Lädt…",
  "common.cancel": "Abbrechen",
  "common.save": "Speichern",
  "common.saved": "Gespeichert.",
  "common.rescan": "Rescan",
  "common.apply": "Übernehmen",
  "common.assign": "Zuweisen",
  "common.previous": "Zurück",
  "common.next": "Weiter",
  "common.pageOf": "Seite {page} von {pages}",

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
  "library.missingOnly": "Nur unvollständige",
  "library.loadError": "Bibliothek konnte nicht geladen werden.",

  "reviewQueue.title": "Unidentifiziert / Review",
  "reviewQueue.empty": "Nichts zu überprüfen.",
  "reviewQueue.review": "Review",
  "reviewQueue.noId": "Keine ID",
  "reviewQueue.manualIdPlaceholder": "AniDB-ID manuell eingeben",

  "duplicates.title": "Dopplung",
  "duplicates.empty": "Keine Dopplungen gefunden.",
  "duplicates.changeId": "ID ändern",
  "duplicates.delete": "Löschen",
  "duplicates.confirmDelete":
    'Eintrag für "{path}" wirklich löschen? Nur der Katalog-Eintrag wird entfernt, die Dateien bleiben unangetastet.',

  "sortQueue.title": "Einsortierung",
  "sortQueue.empty": "Nichts zum Einsortieren.",
  "sortQueue.matchedOf": "{matched}/{total} Episoden zuordenbar",
  "sortQueue.selectFolder": "Ziel-Ordner wählen…",
  "sortQueue.move": "Verschieben",

  "renameQueue.title": "Umbenennung",
  "renameQueue.empty": "Nichts umzubenennen.",
  "renameQueue.mismatchedFiles": "{count} Datei(en) betroffen",
  "renameQueue.rename": "Umbenennen",

  "settings.rescanTitle": "Automatischer Metadaten-Rescan",
  "settings.rescanDescription":
    "Beim Start werden alle identifizierten Serien erneut bei AniDB abgefragt (neue Folgen, geänderte Metadaten) — außer solchen, deren letzte bekannte Folge schon länger als die Schwelle unten zurückliegt (wahrscheinlich abgeschlossen oder abgebrochen, es kommt also vermutlich keine neue Folge mehr).",
  "settings.thresholdLabel": "Schwelle (Tage seit letzter Folge):",
  "settings.thresholdMonths": "≈ {months} Monate",
  "settings.ruleEnabledLabel":
    "Regel aktiv (deaktivieren = alle Serien werden beim Start automatisch aktualisiert, auch bereits als \"No Scan\" markierte — die Markierungen bleiben dabei erhalten, werden nur ignoriert statt gelöscht)",
  "settings.fullRescanTitle": "Vollständiger Rescan",
  "settings.fullRescanDescription":
    "Fragt alle identifizierten Serien sofort erneut bei AniDB ab — ignoriert dabei die Regel oben vollständig, auch für bereits als veraltet markierte Serien.",
  "settings.fullRescanBanWarning":
    "Achtung: Bei einer großen Bibliothek bedeutet das sehr viele Anfragen an AniDB hintereinander — das kann im schlimmsten Fall zu einer vorübergehenden AniDB-Sperre führen.",
  "settings.fullRescanConfirm":
    "Wirklich alle Serien jetzt aktualisieren? Bei einer großen Bibliothek kann das lange dauern und im schlimmsten Fall eine vorübergehende AniDB-Sperre auslösen.",
  "settings.fullRescanButton": "Alle Serien jetzt aktualisieren",
  "settings.fullRescanQueued": "{count} Serien für Rescan eingeplant.",
  "settings.languageTitle": "Sprache",
  "settings.languageDescription": "Sprache der Benutzeroberfläche.",
  "settings.sortModeTitle": "Einsortierung von Download-Ordnern",
  "settings.sortModeDescription":
    "Legt fest, was passiert, wenn eine Serie in einem Download-Ordner identifiziert wurde. \"Nachfragen\" wartet in der Einsortierung-Liste auf einen manuell gewählten Ziel-Ordner. \"Automatisch\" verschiebt sofort, aber nur wenn der Ziel-Ordner eindeutig ist (z.B. schon ein Content-Ordner mit derselben Serie existiert, oder es nur einen Content-Ordner gibt) — sonst landet der Eintrag ebenfalls in der Liste.",
  "settings.sortModeAsk": "Nachfragen",
  "settings.sortModeAuto": "Automatisch",
  "settings.renameModeTitle": "Umbenennung von Ordnern/Episoden",
  "settings.renameModeDescription":
    "Legt fest, was passiert, wenn der Ordner- oder Dateiname eines identifizierten Animes nicht dem Schema \"Titel - S01E{Episode} - Episodentitel\" entspricht. \"Nachfragen\" wartet in der Umbenennung-Liste auf eine Bestätigung. \"Automatisch\" benennt sofort um.",
  "settings.renameModeAsk": "Nachfragen",
  "settings.renameModeAuto": "Automatisch",
  "settings.titleOrderTitle": "Titel-Reihenfolge",
  "settings.titleOrderDescription":
    "Zu jedem Anime kennt AniDB bis zu drei Titel. Hier legst du fest, in welcher Reihenfolge sie verwendet werden — der erste vorhandene gewinnt. Anzeige und Ordnernamen lassen sich getrennt einstellen.",
  "settings.displayTitleOrderLabel": "Anzeigename in der Übersicht",
  "settings.folderTitleOrderLabel": "Ordner- und Dateinamen",
  "settings.titleVariantMain": "Haupttitel (japanisch in westlichen Zeichen)",
  "settings.titleVariantEn": "Originaltitel Englisch",
  "settings.titleVariantJa": "Originaltitel Japanisch",
  "settings.titleOrderMoveUp": "Nach oben",
  "settings.titleOrderMoveDown": "Nach unten",
  "settings.titleOrderFolderHint":
    "Ordner werden dadurch nicht sofort umbenannt — abweichende Namen erscheinen in den Abfragen unter \"Umbenennung\".",

  "animePending.title": "Offene Abfragen zu dieser Serie",
  "animePending.renameTitle": "Umbenennung vorgeschlagen",
  "animePending.folder": "Ordner",
  "animePending.fileCount": "{count} Dateien",
  "animePending.showAll": "Alle {count} anzeigen",
  "animePending.showLess": "Weniger anzeigen",
  "animePending.renameNow": "Jetzt umbenennen",
  "animePending.sortTitle": "Einsortierung offen",
  "animePending.failed": "Fehlgeschlagen: {detail}",

  "missingEpisodes.title": "Fehlende Folgen",
  "missingEpisodes.seriesCount": "{count} Serien unvollständig",
  "missingEpisodes.empty": "Keine fehlenden Folgen — alle identifizierten Serien sind vollständig.",
  "missingEpisodes.presentOfExpected": "{present} von {expected} Folgen vorhanden",
  "missingEpisodes.sectionTitle": "Folgen",
  "missingEpisodes.allPresent": "Alle Folgen der Provider-Liste sind vorhanden.",
  "missingEpisodes.episodeShort": "F{number}",
  "missingEpisodes.showFiles": "Dateien und Nummern anzeigen",
  "missingEpisodes.hideFiles": "Dateien ausblenden",
  "missingEpisodes.correctionHint":
    "Wurde eine Folgennummer falsch oder gar nicht aus dem Dateinamen erkannt, kannst du sie hier korrigieren. Korrigierte Nummern werden bei späteren Scans nicht mehr überschrieben. Leeres Feld speichern setzt die Korrektur zurück.",
  "missingEpisodes.noFiles": "Keine Videodateien erfasst.",
  "missingEpisodes.manual": "Manuell",
  "missingEpisodes.numberPlaceholder": "Nr.",

  "settings.repairScanTitle": "Reparatur-Scan",
  "settings.repairScanDescription":
    "Geht die gesamte Bibliothek durch und ergänzt fehlende Infos aus dem, was lokal schon vorliegt: Titel-Varianten, Jahr, Typ, Beschreibung, Soll-Episodenliste, verlorene Cover-Verknüpfungen und Folgennummern aus den Dateinamen. Bezieht ausdrücklich auch Serien mit \"No Scan\"-Flag ein und fragt dabei nichts bei AniDB ab — also jederzeit gefahrlos. Nur nötig, wenn Daten fehlen oder veraltet wirken.",
  "settings.repairScanButton": "Reparatur-Scan starten",
  "settings.repairScanRunning": "Läuft…",
  "settings.repairScanFailed": "Reparatur-Scan fehlgeschlagen.",
  "settings.repairScanDone": "{count} Serien geprüft.",
  "settings.repairTitles": "Titel-Varianten ergänzt: {count}",
  "settings.repairRenamedTitles": "Anzeigenamen korrigiert: {count}",
  "settings.repairEpisodes": "Folgennummern neu erkannt: {count}",
  "settings.repairMetadata": "Metadaten ergänzt: {count}",
  "settings.repairExpected": "Soll-Episodenlisten ergänzt: {count}",
  "settings.repairPosters": "Cover neu verknüpft: {count}",
  "settings.repairUnrepairable":
    "{count} Serien ohne lokale Daten — dafür hilft nur der vollständige Rescan.",

  "aniDbBan.message": "AniDB hat diese App vorübergehend gesperrt. Identifikation neuer Animes pausiert bis {date}.",

  "animeStatus.identified": "Identifiziert",
  "animeStatus.pending": "Wird verarbeitet…",
  "animeStatus.needsManualId": "Unidentifiziert",
  "animeStatus.review": "Review nötig",

  "animeCard.noArtwork": "Kein Artwork",
  "animeCard.duplicate": "Duplikat",
  "animeCard.complete": "Vollständig",
  "animeCard.missingCount": "{count} fehlend",

  "updateGate.checking": "Prüfe auf Updates…",
  "updateGate.title": "Update verfügbar",
  "updateGate.available": "Version {version} ist verfügbar. Jetzt installieren?",
  "updateGate.installing": "Update wird heruntergeladen und installiert…",
  "updateGate.installFailed": "Installation fehlgeschlagen: {message}",
  "updateGate.skip": "Später",
  "updateGate.install": "Jetzt installieren",

  "emptyFolder.title": "Leeres Verzeichnis gefunden",
  "emptyFolder.description":
    'In "{path}" wurden keine Video-Dateien gefunden. Verzeichnis von der Platte löschen?',
  "emptyFolder.delete": "Löschen",
  "emptyFolder.keep": "Behalten",
}

export type TranslationKey = keyof typeof de

const en: Record<TranslationKey, string> = {
  "nav.library": "Library",
  "nav.missingEpisodes": "Missing episodes",
  "nav.review": "Requests",
  "nav.folders": "Folders",
  "nav.settings": "Settings",

  "common.loading": "Loading…",
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.saved": "Saved.",
  "common.rescan": "Rescan",
  "common.apply": "Apply",
  "common.assign": "Assign",
  "common.previous": "Previous",
  "common.next": "Next",
  "common.pageOf": "Page {page} of {pages}",

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
  "library.missingOnly": "Incomplete only",
  "library.loadError": "Failed to load the library.",

  "reviewQueue.title": "Unidentified / Review",
  "reviewQueue.empty": "Nothing to review.",
  "reviewQueue.review": "Review",
  "reviewQueue.noId": "No ID",
  "reviewQueue.manualIdPlaceholder": "Enter AniDB ID manually",

  "duplicates.title": "Duplicates",
  "duplicates.empty": "No duplicates found.",
  "duplicates.changeId": "Change ID",
  "duplicates.delete": "Delete",
  "duplicates.confirmDelete":
    'Really delete the entry for "{path}"? Only the catalog entry is removed, the files stay untouched.',

  "sortQueue.title": "Sorting",
  "sortQueue.empty": "Nothing to sort.",
  "sortQueue.matchedOf": "{matched}/{total} episodes matched",
  "sortQueue.selectFolder": "Select target folder…",
  "sortQueue.move": "Move",

  "renameQueue.title": "Renaming",
  "renameQueue.empty": "Nothing to rename.",
  "renameQueue.mismatchedFiles": "{count} file(s) affected",
  "renameQueue.rename": "Rename",

  "settings.rescanTitle": "Automatic metadata rescan",
  "settings.rescanDescription":
    "On startup, all identified series are checked against AniDB again (new episodes, changed metadata) — except ones whose last known episode aired longer ago than the threshold below (likely finished or dropped, so a new episode probably isn't coming).",
  "settings.thresholdLabel": "Threshold (days since last episode):",
  "settings.thresholdMonths": "≈ {months} months",
  "settings.ruleEnabledLabel":
    "Rule active (disable = all series are auto-updated on startup, including ones already marked \"No Scan\" — the markers stay in place, just ignored, not deleted)",
  "settings.fullRescanTitle": "Full rescan",
  "settings.fullRescanDescription":
    "Immediately re-checks all identified series against AniDB — completely ignoring the rule above, even for series already marked stale.",
  "settings.fullRescanBanWarning":
    "Warning: for a large library, this means a lot of requests to AniDB in quick succession — in the worst case, that can trigger a temporary AniDB ban.",
  "settings.fullRescanConfirm":
    "Really update all series now? For a large library this can take a while and, in the worst case, trigger a temporary AniDB ban.",
  "settings.fullRescanButton": "Update all series now",
  "settings.fullRescanQueued": "{count} series queued for rescan.",
  "settings.languageTitle": "Language",
  "settings.languageDescription": "User interface language.",
  "settings.sortModeTitle": "Sorting download folders",
  "settings.sortModeDescription":
    "Controls what happens once a series in a download folder is identified. \"Ask\" waits in the sorting list for a manually-picked target folder. \"Automatic\" moves it immediately, but only when the target is unambiguous (e.g. a content folder already has the same series, or there's only one content folder) — otherwise it still lands in the list.",
  "settings.sortModeAsk": "Ask",
  "settings.sortModeAuto": "Automatic",
  "settings.renameModeTitle": "Renaming folders/episodes",
  "settings.renameModeDescription":
    "Controls what happens when an identified anime's folder or file names don't match the \"Title - S01E{episode} - Episode title\" scheme. \"Ask\" waits in the renaming list for confirmation. \"Automatic\" renames immediately.",
  "settings.renameModeAsk": "Ask",
  "settings.renameModeAuto": "Automatic",
  "settings.titleOrderTitle": "Title preference",
  "settings.titleOrderDescription":
    "AniDB knows up to three titles per anime. This sets the order they're used in — the first one that exists wins. The overview name and the on-disk names can be configured separately.",
  "settings.displayTitleOrderLabel": "Display name in the overview",
  "settings.folderTitleOrderLabel": "Folder and file names",
  "settings.titleVariantMain": "Main title (Japanese in Latin script)",
  "settings.titleVariantEn": "Original title, English",
  "settings.titleVariantJa": "Original title, Japanese",
  "settings.titleOrderMoveUp": "Move up",
  "settings.titleOrderMoveDown": "Move down",
  "settings.titleOrderFolderHint":
    "This doesn't rename anything right away — mismatched names show up under \"Renaming\" in the requests tab.",

  "animePending.title": "Open requests for this series",
  "animePending.renameTitle": "Rename suggested",
  "animePending.folder": "Folder",
  "animePending.fileCount": "{count} files",
  "animePending.showAll": "Show all {count}",
  "animePending.showLess": "Show less",
  "animePending.renameNow": "Rename now",
  "animePending.sortTitle": "Sorting pending",
  "animePending.failed": "Failed: {detail}",

  "missingEpisodes.title": "Missing episodes",
  "missingEpisodes.seriesCount": "{count} series incomplete",
  "missingEpisodes.empty": "No missing episodes — every identified series is complete.",
  "missingEpisodes.presentOfExpected": "{present} of {expected} episodes present",
  "missingEpisodes.sectionTitle": "Episodes",
  "missingEpisodes.allPresent": "Every episode on the provider's list is present.",
  "missingEpisodes.episodeShort": "E{number}",
  "missingEpisodes.showFiles": "Show files and numbers",
  "missingEpisodes.hideFiles": "Hide files",
  "missingEpisodes.correctionHint":
    "If an episode number was parsed wrongly from the filename, or not at all, correct it here. Corrected numbers are never overwritten by later scans. Saving an empty field clears the correction.",
  "missingEpisodes.noFiles": "No video files recorded.",
  "missingEpisodes.manual": "Manual",
  "missingEpisodes.numberPlaceholder": "No.",

  "settings.repairScanTitle": "Repair scan",
  "settings.repairScanDescription":
    "Walks the whole library and fills in what is missing from data already held locally: title variants, year, type, description, the expected episode list, lost artwork links, and episode numbers parsed from filenames. Explicitly includes series flagged \"no scan\", and never contacts AniDB — safe to run at any time. Only needed when data is missing or looks outdated.",
  "settings.repairScanButton": "Start repair scan",
  "settings.repairScanRunning": "Running…",
  "settings.repairScanFailed": "Repair scan failed.",
  "settings.repairScanDone": "{count} series checked.",
  "settings.repairTitles": "Title variants filled in: {count}",
  "settings.repairRenamedTitles": "Display names corrected: {count}",
  "settings.repairEpisodes": "Episode numbers re-detected: {count}",
  "settings.repairMetadata": "Metadata filled in: {count}",
  "settings.repairExpected": "Expected episode lists added: {count}",
  "settings.repairPosters": "Artwork re-linked: {count}",
  "settings.repairUnrepairable":
    "{count} series without local data — only a full rescan can help there.",

  "aniDbBan.message": "AniDB has temporarily banned this app. Identification of new anime is paused until {date}.",

  "animeStatus.identified": "Identified",
  "animeStatus.pending": "Processing…",
  "animeStatus.needsManualId": "Unidentified",
  "animeStatus.review": "Needs review",

  "animeCard.noArtwork": "No artwork",
  "animeCard.duplicate": "Duplicate",
  "animeCard.complete": "Complete",
  "animeCard.missingCount": "{count} missing",

  "updateGate.checking": "Checking for updates…",
  "updateGate.title": "Update available",
  "updateGate.available": "Version {version} is available. Install now?",
  "updateGate.installing": "Downloading and installing update…",
  "updateGate.installFailed": "Installation failed: {message}",
  "updateGate.skip": "Later",
  "updateGate.install": "Install now",

  "emptyFolder.title": "Empty directory found",
  "emptyFolder.description":
    'No video files were found in "{path}". Delete the directory from disk?',
  "emptyFolder.delete": "Delete",
  "emptyFolder.keep": "Keep",
}

export const translations: Record<Language, Record<TranslationKey, string>> = { de, en }

export function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  )
}
