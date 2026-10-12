import { useState } from "react"
import {
  useDeleteIntegration,
  useDownloadIntegrations,
  useDownloadPlugins,
  useSaveIntegration,
  useTestIntegration,
} from "@/api/hooks"
import type { DownloadIntegration, DownloadPlugin } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

/** Setup for download clients and search sources. The forms are generated
 * from each plugin's declared settings, so a plugin dropped into the
 * plugins folder gets a working form without any frontend change. */
export function IntegrationsCard() {
  const t = useT()
  const { data: pluginsData } = useDownloadPlugins()
  const { data: integrations } = useDownloadIntegrations()
  const [adding, setAdding] = useState<DownloadPlugin | null>(null)
  const [editing, setEditing] = useState<number | null>(null)

  const plugins = pluginsData?.plugins ?? []
  const pluginById = new Map(plugins.map((p) => [p.id, p]))
  const hasClient = integrations?.some((i) => i.kind === "client" && i.enabled) ?? false

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="space-y-1">
          <p className="text-sm font-medium">{t("downloads.setupTitle")}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("downloads.setupDescription")}</p>
        </div>

        {integrations && !hasClient && (
          <p className="text-sm text-amber-600 dark:text-amber-400">{t("downloads.noClients")}</p>
        )}

        <div className="space-y-2">
          {integrations?.map((integration) =>
            editing === integration.id && pluginById.has(integration.plugin_id) ? (
              <IntegrationForm
                key={integration.id}
                plugin={pluginById.get(integration.plugin_id)!}
                integration={integration}
                onDone={() => setEditing(null)}
              />
            ) : (
              <IntegrationRow
                key={integration.id}
                integration={integration}
                plugin={pluginById.get(integration.plugin_id)}
                onEdit={() => setEditing(integration.id)}
              />
            ),
          )}
        </div>

        {adding ? (
          <IntegrationForm plugin={adding} onDone={() => setAdding(null)} />
        ) : (
          <select
            value=""
            onChange={(e) => setAdding(pluginById.get(e.target.value) ?? null)}
            className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
          >
            <option value="">{t("downloads.addPlaceholder")}</option>
            {plugins.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.kind === "client" ? t("downloads.kindClient") : t("downloads.kindSource")}
                {p.builtin ? `, ${t("downloads.builtin")}` : ""})
              </option>
            ))}
          </select>
        )}

        {pluginsData && (
          <div className="space-y-1 text-xs text-[hsl(var(--muted-foreground))]">
            <p>{t("downloads.pluginsFolder", { path: pluginsData.plugins_folder })}</p>
            {pluginsData.load_errors.length > 0 && (
              <div className="text-amber-600 dark:text-amber-400">
                <p>{t("downloads.loadErrors")}</p>
                <ul className="list-inside list-disc">
                  {pluginsData.load_errors.map((e) => (
                    <li key={e.file}>
                      {e.file}: {e.error}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function IntegrationRow({
  integration,
  plugin,
  onEdit,
}: {
  integration: DownloadIntegration
  plugin: DownloadPlugin | undefined
  onEdit: () => void
}) {
  const t = useT()
  const test = useTestIntegration()
  const remove = useDeleteIntegration()

  return (
    <div className="space-y-1 rounded border p-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className={integration.enabled ? "truncate font-medium" : "truncate text-[hsl(var(--muted-foreground))] line-through"}>
            {integration.name}
          </span>
          <Badge variant="outline">
            {integration.kind === "source" ? t("downloads.kindSource") : t("downloads.kindClient")}
          </Badge>
          <span className="truncate text-xs text-[hsl(var(--muted-foreground))]">
            {plugin ? plugin.name : t("downloads.pluginMissing")}
          </span>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button size="sm" variant="outline" disabled={!plugin || test.isPending} onClick={() => test.mutate(integration.id)}>
            {t("downloads.test")}
          </Button>
          <Button size="sm" variant="ghost" disabled={!plugin} onClick={onEdit}>
            {t("downloads.edit")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={remove.isPending}
            onClick={() => {
              if (confirm(t("downloads.deleteConfirm", { name: integration.name }))) remove.mutate(integration.id)
            }}
          >
            {t("downloads.delete")}
          </Button>
        </div>
      </div>
      {test.data && (
        <p className={test.data.ok ? "text-xs text-emerald-600" : "text-xs text-red-500"}>{test.data.message}</p>
      )}
    </div>
  )
}

function IntegrationForm({
  plugin,
  integration,
  onDone,
}: {
  plugin: DownloadPlugin
  integration?: DownloadIntegration
  onDone: () => void
}) {
  const t = useT()
  const save = useSaveIntegration()
  const [name, setName] = useState(integration?.name ?? plugin.name)
  const [enabled, setEnabled] = useState(integration?.enabled ?? true)
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {}
    for (const field of plugin.settings_schema) {
      initial[field.key] = integration ? (integration.config[field.key] ?? "") : (field.default ?? "")
      if (field.type === "bool") initial[field.key] = Boolean(initial[field.key])
    }
    return initial
  })

  const setValue = (key: string, value: unknown) => setValues((prev) => ({ ...prev, [key]: value }))

  const submit = () => {
    const config: Record<string, unknown> = {}
    for (const field of plugin.settings_schema) {
      const value = values[field.key]
      config[field.key] = field.type === "number" && value !== "" ? Number(value) : value
    }
    save.mutate({ id: integration?.id, pluginId: plugin.id, name, enabled, config }, { onSuccess: onDone })
  }

  return (
    <div className="space-y-3 rounded border border-[hsl(var(--primary))] p-3 text-sm">
      <div className="space-y-0.5">
        <p className="font-medium">{plugin.name}</p>
        {plugin.description && <p className="text-xs text-[hsl(var(--muted-foreground))]">{plugin.description}</p>}
      </div>

      <label className="block space-y-1">
        <span className="text-xs">{t("downloads.name")}</span>
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </label>

      {plugin.settings_schema.map((field) =>
        field.type === "bool" ? (
          <label key={field.key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={Boolean(values[field.key])}
              onChange={(e) => setValue(field.key, e.target.checked)}
            />
            {field.label}
          </label>
        ) : (
          <label key={field.key} className="block space-y-1">
            <span className="text-xs">
              {field.label}
              {field.required && " *"}
            </span>
            <Input
              type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
              value={String(values[field.key] ?? "")}
              placeholder={
                field.type === "password" && integration?.secrets_set.includes(field.key)
                  ? t("downloads.passwordSet")
                  : undefined
              }
              onChange={(e) => setValue(field.key, e.target.value)}
            />
            {field.help && <span className="block text-xs text-[hsl(var(--muted-foreground))]">{field.help}</span>}
          </label>
        ),
      )}

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        {t("downloads.enabled")}
      </label>

      {save.isError && <p className="text-xs text-red-500">{t("downloads.failed", { message: save.error.message })}</p>}

      <div className="flex gap-2">
        <Button size="sm" onClick={submit} disabled={save.isPending}>
          {t("common.save")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          {t("common.cancel")}
        </Button>
      </div>
    </div>
  )
}
