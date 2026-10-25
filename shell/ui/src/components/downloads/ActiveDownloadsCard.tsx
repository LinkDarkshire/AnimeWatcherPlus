import { Link } from "react-router-dom"
import { useActiveDownloads, useClearFinishedDownloads, useDismissDownload } from "@/api/hooks"
import type { ActiveDownload, DownloadState } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { formatSize } from "@/lib/format"
import { useT } from "@/i18n/I18nContext"
import type { TranslationKey } from "@/i18n/translations"

const STATE_LABELS: Record<DownloadState, TranslationKey> = {
  resolving: "downloads.state.resolving",
  queued: "downloads.state.queued",
  downloading: "downloads.state.downloading",
  paused: "downloads.state.paused",
  seeding: "downloads.state.seeding",
  finished: "downloads.state.finished",
  error: "downloads.state.error",
  unknown: "downloads.state.unknown",
}

const STATE_COLORS: Partial<Record<DownloadState, string>> = {
  resolving: "animate-pulse bg-amber-500",
  downloading: "bg-sky-500",
  seeding: "bg-emerald-500",
  finished: "bg-emerald-500",
  error: "bg-red-500",
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

/** Live progress of recently sent downloads, read straight from the clients --
 * the only place to see it when those run in a container somewhere else. */
export function ActiveDownloadsCard() {
  const t = useT()
  const { data: downloads } = useActiveDownloads()
  const dismiss = useDismissDownload()
  const clear = useClearFinishedDownloads()

  if (!downloads || downloads.length === 0) return null
  const doneCount = downloads.filter((d) => d.status.state === "finished" || d.status.state === "seeding").length

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium">{t("downloads.activeTitle")}</p>
          {doneCount > 0 && (
            <Button size="sm" variant="outline" disabled={clear.isPending} onClick={() => clear.mutate()}>
              {t("downloads.clearFinished", { count: doneCount })}
            </Button>
          )}
        </div>
        {clear.data && (
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            {t("downloads.clearedFinished", {
              hidden: clear.data.hidden,
              removed: clear.data.removed_from_clients,
            })}
            {clear.data.errors.length > 0 && (
              <span className="block text-amber-600 dark:text-amber-400">{clear.data.errors.join(" · ")}</span>
            )}
          </p>
        )}
        {downloads.map((download) => (
          <ActiveRow
            key={download.request_id}
            download={download}
            label={t(STATE_LABELS[download.status.state])}
            dismissing={dismiss.isPending && dismiss.variables === download.request_id}
            onDismiss={() => dismiss.mutate(download.request_id)}
          />
        ))}
      </CardContent>
    </Card>
  )
}

function ActiveRow({
  download,
  label,
  dismissing,
  onDismiss,
}: {
  download: ActiveDownload
  label: string
  dismissing: boolean
  onDismiss: () => void
}) {
  const t = useT()
  const { status } = download
  const percent = status.progress !== null ? Math.round(status.progress * 100) : null
  const speed = status.speed_bps ? `${formatSize(status.speed_bps)}/s` : null
  const eta = status.eta_seconds !== null ? t("downloads.eta", { time: formatDuration(status.eta_seconds) }) : null
  const meta = [download.client_name, percent !== null ? `${percent} %` : null, speed, eta, status.message].filter(
    Boolean,
  )

  return (
    <div className="space-y-1 rounded border p-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {download.anime_id ? (
            <Link to={`/animes/${download.anime_id}`} className="truncate hover:underline">
              {download.title}
            </Link>
          ) : (
            <span className="truncate">{download.title}</span>
          )}
          <Badge variant={status.state === "error" ? "destructive" : "outline"}>{label}</Badge>
        </div>
        <Button size="sm" variant="ghost" disabled={dismissing} onClick={onDismiss}>
          {t("downloads.hide")}
        </Button>
      </div>
      {percent !== null && (
        <div className="h-1.5 overflow-hidden rounded bg-[hsl(var(--muted))]">
          <div
            className={`h-full ${STATE_COLORS[status.state] ?? "bg-[hsl(var(--muted-foreground))]"}`}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}
      <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">{meta.join(" · ")}</p>
    </div>
  )
}
