import { useAniDbStatus } from "@/api/hooks"
import type { AniDbStatus } from "@/api/types"
import { useLanguage, useT } from "@/i18n/I18nContext"
import type { TranslationKey } from "@/i18n/translations"
import { cn } from "@/lib/utils"

const LOCALE_BY_LANGUAGE: Record<string, string> = { de: "de-DE", en: "en-US" }

const BLOCKED_LABELS: Record<NonNullable<AniDbStatus["blocked_reason"]>, TranslationKey> = {
  ban: "anidb.blocked.ban",
  daily_cap: "anidb.blocked.daily_cap",
  paused: "anidb.blocked.paused",
}

/** "Resuming after a block" stays visible this long after the work was re-queued. */
const RESUMED_HINT_MS = 15 * 60 * 1000

/** Header indicator: shows when the core is actually talking to AniDB (not
 * cache hits), what it is looking up, rate-limit waits, queued work, and --
 * after a ban or the daily limit -- until when it's blocked and that it
 * picks up again afterwards. Hidden while nothing at all is going on. */
export function AniDbActivity() {
  const t = useT()
  const { language } = useLanguage()
  const { data: status } = useAniDbStatus()
  if (!status) return null

  const waitingTotal = status.waiting_anime + status.waiting_wishlist
  const formatTime = (epoch: number) => {
    const date = new Date(epoch * 1000)
    const sameDay = date.toDateString() === new Date().toDateString()
    return sameDay
      ? date.toLocaleTimeString(LOCALE_BY_LANGUAGE[language], { hour: "2-digit", minute: "2-digit" })
      : date.toLocaleString(LOCALE_BY_LANGUAGE[language], { dateStyle: "short", timeStyle: "short" })
  }

  let text: string | null = null
  let tone: "active" | "blocked" | "muted" = "muted"
  if (status.blocked_reason && status.blocked_until) {
    tone = "blocked"
    text = t(BLOCKED_LABELS[status.blocked_reason], { time: formatTime(status.blocked_until) })
    if (waitingTotal > 0) text += ` · ${t("anidb.waitingAfterBlock", { count: waitingTotal })}`
  } else if (status.state === "requesting" && status.detail) {
    tone = "active"
    text = t("anidb.requesting", { detail: status.detail })
  } else if (status.state === "waiting" && status.detail) {
    tone = "active"
    text = t("anidb.waiting", { detail: status.detail, seconds: Math.ceil(status.wait_seconds ?? 0) })
  } else if (status.queued_jobs > 0) {
    text = t("anidb.queued", { count: status.queued_jobs })
  }
  if (text === null) return null

  if (tone === "active" && status.queued_jobs > 1) {
    text += ` · ${t("anidb.more", { count: status.queued_jobs - 1 })}`
  }
  const resumedRecently =
    !status.blocked_reason &&
    status.resumed_at !== null &&
    Date.now() - status.resumed_at * 1000 < RESUMED_HINT_MS
  if (resumedRecently) text = `${text} (${t("anidb.resumed")})`

  const tooltip = t("anidb.tooltip", {
    today: status.requests_today,
    cap: status.daily_cap ? ` / ${status.daily_cap}` : "",
    anime: status.waiting_anime,
    wishlist: status.waiting_wishlist,
  })

  return (
    <div
      title={tooltip}
      className={cn(
        "ml-auto flex min-w-0 items-center gap-2 text-xs",
        tone === "blocked" ? "text-amber-600 dark:text-amber-400" : "text-[hsl(var(--muted-foreground))]",
      )}
    >
      <span
        className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          tone === "active" && "animate-pulse bg-sky-500",
          tone === "blocked" && "bg-amber-500",
          tone === "muted" && "bg-[hsl(var(--muted-foreground))]",
        )}
      />
      <span className="truncate">{text}</span>
    </div>
  )
}
