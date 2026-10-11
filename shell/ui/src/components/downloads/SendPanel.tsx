import { useState } from "react"
import { openExternal } from "@/api/client"
import {
  useDownloadIntegrations,
  useDownloadReleases,
  useDownloadSearch,
  useFolders,
  useSendDownload,
} from "@/api/hooks"
import type { DownloadSearchResult, DownloadTarget } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { formatSize } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

/** Search the configured sources for one episode/series and hand a link
 * (found or pasted) to a download client. */
export function SendPanel({ target }: { target: DownloadTarget }) {
  const t = useT()
  const { data: integrations } = useDownloadIntegrations()
  const { data: folders } = useFolders()
  const search = useDownloadSearch()
  const releases = useDownloadReleases()
  const send = useSendDownload()

  const clients = integrations?.filter((i) => i.kind === "client" && i.enabled) ?? []
  const hasSources = integrations?.some((i) => i.kind === "source" && i.enabled) ?? false
  const downloadFolders = folders?.filter((f) => f.type === "download" && f.active) ?? []

  const [clientId, setClientId] = useState<number | undefined>(undefined)
  const [folderId, setFolderId] = useState<number | undefined>(undefined)
  const [link, setLink] = useState("")

  const selectedClient = clientId ?? clients[0]?.id
  const selectedFolder = folderId ?? downloadFolders[0]?.id

  const sendLink = (value: string) => {
    if (selectedClient === undefined || !value.trim()) return
    send.mutate(
      { ...target, client_id: selectedClient, link: value.trim(), folder_id: selectedFolder },
      { onSuccess: () => setLink("") },
    )
  }

  const selectClass = "h-8 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-xs"

  return (
    <div className="space-y-2 rounded-md bg-[hsl(var(--muted))] p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={selectedClient ?? ""}
          onChange={(e) => setClientId(Number(e.target.value))}
          className={selectClass}
          disabled={clients.length === 0}
        >
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {downloadFolders.length > 1 && (
          <label className="flex items-center gap-1 text-xs">
            {t("downloads.folder")}
            <select value={selectedFolder} onChange={(e) => setFolderId(Number(e.target.value))} className={selectClass}>
              {downloadFolders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {hasSources && (
          <Button
            size="sm"
            variant="outline"
            disabled={search.isPending}
            onClick={() => {
              releases.reset()
              search.mutate(target)
            }}
          >
            {search.isPending ? t("downloads.searching") : t("downloads.search")}
          </Button>
        )}
      </div>

      {clients.length === 0 && <p className="text-xs text-amber-600 dark:text-amber-400">{t("downloads.noClients")}</p>}
      {folders && downloadFolders.length === 0 && (
        <p className="text-xs text-amber-600 dark:text-amber-400">{t("downloads.noDownloadFolder")}</p>
      )}

      {search.data && (
        <div className="space-y-1">
          {Object.entries({ ...search.data.notes, ...(releases.data?.notes ?? {}) }).map(([source, note]) => (
            <p key={`note-${source}`} className="text-xs text-[hsl(var(--muted-foreground))]">
              {t("downloads.sourceError", { source, error: note })}
            </p>
          ))}
          {Object.entries({ ...search.data.errors, ...(releases.data?.errors ?? {}) }).map(([source, error]) => (
            <p key={source} className="text-xs text-red-500">
              {t("downloads.sourceError", { source, error })}
            </p>
          ))}

          {/* Two-stage sources with several matching series: pick one first. */}
          {search.data.series.length > 0 && !releases.data && (
            <div className="space-y-1">
              <p className="text-xs">{t("downloads.pickSeries")}</p>
              {search.data.series.map((series) => (
                <div
                  key={`${series.integration_id}-${series.url}`}
                  className="flex items-center justify-between gap-2 rounded border bg-[hsl(var(--background))] p-2"
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium">{series.title}</p>
                    <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">
                      {series.source_name} · {series.url}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={releases.isPending}
                    onClick={() => releases.mutate({ target, series })}
                  >
                    {releases.isPending && releases.variables?.series.url === series.url
                      ? t("downloads.searching")
                      : t("downloads.pick")}
                  </Button>
                </div>
              ))}
            </div>
          )}
          {releases.data && search.data.series.length > 0 && (
            <Button size="sm" variant="ghost" onClick={() => releases.reset()}>
              {t("downloads.otherSeries")}
            </Button>
          )}

          {(releases.data ?? search.data).results.length === 0 &&
            (releases.data || search.data.series.length === 0) &&
            Object.keys(search.data.notes).length === 0 && (
              <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("downloads.noResults")}</p>
            )}
          {[...search.data.results, ...(releases.data?.results ?? [])].map((result, index) => (
            <ResultRow
              key={`${result.link}-${index}`}
              result={result}
              canSend={selectedClient !== undefined && !send.isPending}
              onSend={() => sendLink(result.link)}
            />
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <Input
          value={link}
          onChange={(e) => setLink(e.target.value)}
          placeholder={t("downloads.linkPlaceholder")}
          className="h-8 text-xs"
          onKeyDown={(e) => {
            if (e.key === "Enter") sendLink(link)
          }}
        />
        <Button
          size="sm"
          disabled={selectedClient === undefined || !link.trim() || send.isPending}
          onClick={() => sendLink(link)}
        >
          {t("downloads.send")}
        </Button>
      </div>

      {send.isSuccess && (
        <p className="text-xs text-emerald-600">{t("downloads.sent", { client: send.data.client_name })}</p>
      )}
      {send.isError && <p className="text-xs text-red-500">{t("downloads.failed", { message: send.error.message })}</p>}
    </div>
  )
}

function ResultRow({
  result,
  canSend,
  onSend,
}: {
  result: DownloadSearchResult
  canSend: boolean
  onSend: () => void
}) {
  const t = useT()
  const meta = [
    result.source_name,
    result.hoster,
    formatSize(result.size_bytes),
    result.seeders !== null ? t("downloads.seeders", { count: result.seeders }) : null,
    result.published,
    ...Object.entries(result.details).map(([label, value]) => (label ? `${label}: ${value}` : value)),
  ].filter(Boolean)

  return (
    <div className="flex items-center justify-between gap-2 rounded border bg-[hsl(var(--background))] p-2">
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 truncate text-xs font-medium">
          {result.title}
          {result.kind === "stream" && <Badge variant="outline">{t("downloads.stream")}</Badge>}
        </p>
        <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">{meta.join(" · ")}</p>
        {result.needs_browser && result.kind === "download" && (
          <p className="text-xs text-amber-600 dark:text-amber-400">{t("downloads.browserHint")}</p>
        )}
      </div>
      {result.kind === "stream" ? (
        <Button size="sm" variant="outline" onClick={() => void openExternal(result.link)}>
          {t("downloads.open")}
        </Button>
      ) : result.needs_browser ? (
        <Button size="sm" variant="outline" onClick={() => void openExternal(result.link)}>
          {t("downloads.openInBrowser")}
        </Button>
      ) : (
        <Button size="sm" disabled={!canSend} onClick={onSend}>
          {t("downloads.send")}
        </Button>
      )}
    </div>
  )
}
