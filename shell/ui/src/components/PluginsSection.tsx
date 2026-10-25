import { useDownloadPlugins, useReloadPlugins } from "@/api/hooks"
import { useFolderOpener, useShellConnection } from "@/api/shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { KIND_LABELS } from "@/lib/pluginKinds"
import { useT } from "@/i18n/I18nContext"

const muted = "text-xs text-[hsl(var(--muted-foreground))]"

/** Which download plugins the plugins folder holds right now, which failed
 * to load and why -- with the folder itself and a reload for plugins added
 * while the app (or the server) is running. */
export function PluginsSection() {
  const t = useT()
  const { data } = useDownloadPlugins()
  const reload = useReloadPlugins()
  const folders = useFolderOpener()
  const { data: connection } = useShellConnection()

  if (!data) return null
  const own = data.plugins.filter((p) => !p.builtin)
  const localFolder = folders.localPath(data.plugins_folder)
  const onServer = connection?.mode === "server" && connection.platform === "desktop"

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <p className="text-sm font-medium">{t("plugins.title")}</p>
        <p className={muted}>{t(onServer ? "plugins.descriptionServer" : "plugins.description")}</p>
        <p className="font-mono text-xs break-all">{data.plugins_folder}</p>

        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={reload.isPending} onClick={() => reload.mutate()}>
            {reload.isPending ? t("plugins.reloading") : t("plugins.reload")}
          </Button>
          {localFolder && (
            <Button size="sm" variant="outline" onClick={() => folders.open(data.plugins_folder)}>
              {t("plugins.openFolder")}
            </Button>
          )}
        </div>
        {onServer && !localFolder && <p className={muted}>{t("plugins.mapFolderHint")}</p>}
        {reload.isError && <p className="text-xs text-red-500">{reload.error.message}</p>}

        {own.length === 0 && data.load_errors.length === 0 && <p className="text-sm">{t("plugins.none")}</p>}
        {own.length > 0 && (
          <ul className="divide-y divide-[hsl(var(--border))]">
            {own.map((plugin) => (
              <li key={plugin.id} className="flex flex-wrap items-center gap-2 py-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{plugin.name}</p>
                  <p className={`font-mono ${muted}`}>
                    {plugin.file} · {plugin.id}
                  </p>
                </div>
                <Badge variant="outline">{t(KIND_LABELS[plugin.kind])}</Badge>
              </li>
            ))}
          </ul>
        )}
        {data.load_errors.length > 0 && (
          <div className="space-y-1">
            <p className="text-sm text-red-500">{t("plugins.loadErrors")}</p>
            {data.load_errors.map((error) => (
              <p key={error.file} className="text-xs break-words">
                <span className="font-mono">{error.file}</span>: {error.error}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
