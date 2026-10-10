import { useState } from "react"
import { useDownloadIntegrations, useDownloadSearch, useFolders, useSendDownload } from "@/api/hooks"
import type { DownloadTarget } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

function formatSize(bytes: number | null): string | null {
  if (!bytes) return null
  const units = ["B", "KB", "MB", "GB", "TB"]
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

/** Search the configured sources for one episode/series and hand a link
 * (found or pasted) to a download client. */
export function SendPanel({ target }: { target: DownloadTarget }) {
  const t = useT()
  const { data: integrations } = useDownloadIntegrations()
  const { data: folders } = useFolders()
  const search = useDownloadSearch()
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
          <Button size="sm" variant="outline" disabled={search.isPending} onClick={() => search.mutate(target)}>
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
          {Object.entries(search.data.errors).map(([source, error]) => (
            <p key={source} className="text-xs text-red-500">
              {t("downloads.sourceError", { source, error })}
            </p>
          ))}
          {search.data.results.length === 0 && (
            <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("downloads.noResults")}</p>
          )}
          {search.data.results.map((result, index) => {
            const meta = [
              result.source_name,
              formatSize(result.size_bytes),
              result.seeders !== null ? t("downloads.seeders", { count: result.seeders }) : null,
              result.published,
            ].filter(Boolean)
            return (
              <div
                key={`${result.link}-${index}`}
                className="flex items-center justify-between gap-2 rounded border bg-[hsl(var(--background))] p-2"
              >
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{result.title}</p>
                  <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">{meta.join(" · ")}</p>
                </div>
                <Button
                  size="sm"
                  disabled={selectedClient === undefined || send.isPending}
                  onClick={() => sendLink(result.link)}
                >
                  {t("downloads.send")}
                </Button>
              </div>
            )
          })}
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
