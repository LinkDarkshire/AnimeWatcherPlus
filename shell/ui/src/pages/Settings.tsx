import { useEffect, useState } from "react"
import { useRescanAll, useSettings, useUpdateSettings } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"

const THRESHOLD_KEY = "staleness_threshold_days"
const ENABLED_KEY = "staleness_rule_enabled"
const DEFAULT_THRESHOLD_DAYS = 182 // ~6 Monate

export function Settings() {
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
      <h1 className="text-lg font-semibold">Einstellungen</h1>
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">Lädt…</p>}

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">Automatischer Metadaten-Rescan</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Beim Start werden alle identifizierten Serien erneut bei AniDB abgefragt (neue Folgen,
            geänderte Metadaten) — außer solchen, deren letzte bekannte Folge schon länger als die
            Schwelle unten zurückliegt (wahrscheinlich abgeschlossen oder abgebrochen, es kommt
            also vermutlich keine neue Folge mehr).
          </p>

          <div className="flex items-center gap-2">
            <label htmlFor="threshold" className="text-sm">
              Schwelle (Tage seit letzter Folge):
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
              ≈ {(Number(threshold) / 30.44).toFixed(1)} Monate
            </span>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Regel aktiv (deaktivieren = alle Serien werden beim Start immer automatisch aktualisiert)
          </label>

          <Button size="sm" onClick={handleSave} disabled={updateSettings.isPending}>
            Speichern
          </Button>
          {updateSettings.isSuccess && <p className="text-xs text-emerald-600">Gespeichert.</p>}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">Vollständiger Rescan</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Fragt alle identifizierten Serien sofort erneut bei AniDB ab — ignoriert dabei die
            Regel oben vollständig, auch für bereits als veraltet markierte Serien.
          </p>
          <Button size="sm" variant="outline" onClick={() => rescanAll.mutate()} disabled={rescanAll.isPending}>
            Alle Serien jetzt aktualisieren
          </Button>
          {rescanAll.isSuccess && (
            <p className="text-xs text-emerald-600">{rescanAll.data.queued} Serien für Rescan eingeplant.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
