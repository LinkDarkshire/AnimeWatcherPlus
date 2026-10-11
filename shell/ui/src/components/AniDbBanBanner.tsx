import { useSettings } from "@/api/hooks"
import { useLanguage, useT } from "@/i18n/I18nContext"

const LOCALE_BY_LANGUAGE: Record<string, string> = { de: "de-DE", en: "en-US" }

/** Shown while AniDB has banned this client. During a ban nothing can be
 * identified, and without this banner that would just look broken. */
export function AniDbBanBanner() {
  const t = useT()
  const { language } = useLanguage()
  const { data } = useSettings()
  const bannedUntilRaw = data?.values?.anidb_banned_until
  const bannedUntil = typeof bannedUntilRaw === "number" ? bannedUntilRaw : null

  if (!bannedUntil || bannedUntil * 1000 <= Date.now()) return null

  const resumeAt = new Date(bannedUntil * 1000)

  return (
    <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
      {t("aniDbBan.message", { date: resumeAt.toLocaleString(LOCALE_BY_LANGUAGE[language]) })}
    </div>
  )
}
