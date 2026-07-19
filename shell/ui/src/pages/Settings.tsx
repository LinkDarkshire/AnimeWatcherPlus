import { useEffect, useState } from "react"
import { useRescanAll, useSettings, useUpdateSettings } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { useLanguage, useT } from "@/i18n/I18nContext"
import { LANGUAGES, type Language } from "@/i18n/translations"

const THRESHOLD_KEY = "staleness_threshold_days"
const ENABLED_KEY = "staleness_rule_enabled"
const DEFAULT_THRESHOLD_DAYS = 182 // ~6 Monate

export function Settings() {
  const t = useT()
  const { language, setLanguage } = useLanguage()
  const { data: settings, isLoading } = useSettings()
  const updateSettings = useUpdateSettings()
  const rescanAll = useRescanAll()

  const [threshold, setThreshold] = useState(String(DEFAULT_THRESHOLD_DAYS))
  const [enabled, setEnabled] = useState(true)

  useEffect(() => {
    const storedThreshold = settings?.values[THRESHOLD_KEY]
    const storedEnabled = settings?.values[ENABLED_KEY]
    if (typeof storedThreshold === "number") setThreshold(String(storedThreshold))
    if (typeof storedEnabled === "boolean") setEnabled(storedEnabled)
  }, [settings])

  const handleSave = () => {
    updateSettings.mutate({
      [THRESHOLD_KEY]: Number(threshold) || DEFAULT_THRESHOLD_DAYS,
      [ENABLED_KEY]: enabled,
    })
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4">
      <h1 className="text-lg font-semibold">{t("nav.settings")}</h1>
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">{t("settings.languageTitle")}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("settings.languageDescription")}</p>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as Language)}
            className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
          >
            {Object.entries(LANGUAGES).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">{t("settings.rescanTitle")}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("settings.rescanDescription")}</p>

          <div className="flex items-center gap-2">
            <label htmlFor="threshold" className="text-sm">
              {t("settings.thresholdLabel")}
            </label>
            <Input
              id="threshold"
              type="number"
              min={1}
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="w-28"
              disabled={!enabled}
            />
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              {t("settings.thresholdMonths", { months: (Number(threshold) / 30.44).toFixed(1) })}
            </span>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            {t("settings.ruleEnabledLabel")}
          </label>

          <Button size="sm" onClick={handleSave} disabled={updateSettings.isPending}>
            {t("common.save")}
          </Button>
          {updateSettings.isSuccess && <p className="text-xs text-emerald-600">{t("common.saved")}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">{t("settings.fullRescanTitle")}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("settings.fullRescanDescription")}</p>
          <Button size="sm" variant="outline" onClick={() => rescanAll.mutate()} disabled={rescanAll.isPending}>
            {t("settings.fullRescanButton")}
          </Button>
          {rescanAll.isSuccess && (
            <p className="text-xs text-emerald-600">
              {t("settings.fullRescanQueued", { count: rescanAll.data.queued })}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
