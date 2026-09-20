import { useEffect, useState } from "react"
import { useRepairScan, useRescanAll, useSettings, useUpdateSettings } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { TitleOrderPicker } from "@/components/TitleOrderPicker"
import { DEFAULT_TITLE_ORDER, normalizeTitleOrder, type TitleVariant } from "@/lib/titleOrder"
import { useLanguage, useT } from "@/i18n/I18nContext"
import { LANGUAGES, type Language } from "@/i18n/translations"

const THRESHOLD_KEY = "staleness_threshold_days"
const ENABLED_KEY = "staleness_rule_enabled"
const DEFAULT_THRESHOLD_DAYS = 182 // ~6 Monate

const SORT_MODE_KEY = "sort_mode"
const DEFAULT_SORT_MODE = "ask"

const RENAME_MODE_KEY = "rename_mode"
const DEFAULT_RENAME_MODE = "ask"

const DISPLAY_TITLE_ORDER_KEY = "display_title_order"
const FOLDER_TITLE_ORDER_KEY = "folder_title_order"

export function Settings() {
  const t = useT()
  const { language, setLanguage } = useLanguage()
  const { data: settings, isLoading } = useSettings()
  const updateSettings = useUpdateSettings()
  const rescanAll = useRescanAll()
  const repairScan = useRepairScan()

  const [threshold, setThreshold] = useState(String(DEFAULT_THRESHOLD_DAYS))
  const [enabled, setEnabled] = useState(true)
  const [sortMode, setSortMode] = useState(DEFAULT_SORT_MODE)
  const [renameMode, setRenameMode] = useState(DEFAULT_RENAME_MODE)
  const [displayTitleOrder, setDisplayTitleOrder] = useState<TitleVariant[]>(DEFAULT_TITLE_ORDER)
  const [folderTitleOrder, setFolderTitleOrder] = useState<TitleVariant[]>(DEFAULT_TITLE_ORDER)

  useEffect(() => {
    const storedThreshold = settings?.values[THRESHOLD_KEY]
    const storedEnabled = settings?.values[ENABLED_KEY]
    const storedSortMode = settings?.values[SORT_MODE_KEY]
    const storedRenameMode = settings?.values[RENAME_MODE_KEY]
    if (typeof storedThreshold === "number") setThreshold(String(storedThreshold))
    if (typeof storedEnabled === "boolean") setEnabled(storedEnabled)
    if (typeof storedSortMode === "string") setSortMode(storedSortMode)
    if (typeof storedRenameMode === "string") setRenameMode(storedRenameMode)
    if (settings) {
      setDisplayTitleOrder(normalizeTitleOrder(settings.values[DISPLAY_TITLE_ORDER_KEY]))
      setFolderTitleOrder(normalizeTitleOrder(settings.values[FOLDER_TITLE_ORDER_KEY]))
    }
  }, [settings])

  const handleSave = () => {
    updateSettings.mutate({
      [THRESHOLD_KEY]: Number(threshold) || DEFAULT_THRESHOLD_DAYS,
      [ENABLED_KEY]: enabled,
    })
  }

  const handleSaveSortMode = (value: string) => {
    setSortMode(value)
    updateSettings.mutate({ [SORT_MODE_KEY]: value })
  }

  const handleSaveRenameMode = (value: string) => {
    setRenameMode(value)
    updateSettings.mutate({ [RENAME_MODE_KEY]: value })
  }

  // Saved explicitly, unlike the single-value settings: applying an order
  // re-resolves the display name of every anime in the library, which must
  // not happen once per arrow click while the user is still arranging them.
  const storedDisplayOrder = normalizeTitleOrder(settings?.values[DISPLAY_TITLE_ORDER_KEY])
  const storedFolderOrder = normalizeTitleOrder(settings?.values[FOLDER_TITLE_ORDER_KEY])
  const titleOrderDirty =
    displayTitleOrder.join() !== storedDisplayOrder.join() ||
    folderTitleOrder.join() !== storedFolderOrder.join()

  const handleSaveTitleOrders = () => {
    updateSettings.mutate({
      [DISPLAY_TITLE_ORDER_KEY]: displayTitleOrder,
      [FOLDER_TITLE_ORDER_KEY]: folderTitleOrder,
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
        <CardContent className="space-y-4 p-4">
          <div className="space-y-1">
            <p className="text-sm font-medium">{t("settings.titleOrderTitle")}</p>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              {t("settings.titleOrderDescription")}
            </p>
          </div>
          <TitleOrderPicker
            label={t("settings.displayTitleOrderLabel")}
            value={displayTitleOrder}
            disabled={updateSettings.isPending}
            onChange={setDisplayTitleOrder}
          />
          <TitleOrderPicker
            label={t("settings.folderTitleOrderLabel")}
            hint={t("settings.titleOrderFolderHint")}
            value={folderTitleOrder}
            disabled={updateSettings.isPending}
            onChange={setFolderTitleOrder}
          />
          <Button
            size="sm"
            onClick={handleSaveTitleOrders}
            disabled={!titleOrderDirty || updateSettings.isPending}
          >
            {t("common.save")}
          </Button>
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
          <p className="text-xs text-amber-600 dark:text-amber-400">{t("settings.fullRescanBanWarning")}</p>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (confirm(t("settings.fullRescanConfirm"))) rescanAll.mutate()
            }}
            disabled={rescanAll.isPending}
          >
            {t("settings.fullRescanButton")}
          </Button>
          {rescanAll.isSuccess && (
            <p className="text-xs text-emerald-600">
              {t("settings.fullRescanQueued", { count: rescanAll.data.queued })}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">{t("settings.sortModeTitle")}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("settings.sortModeDescription")}</p>
          <select
            value={sortMode}
            onChange={(e) => handleSaveSortMode(e.target.value)}
            className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
          >
            <option value="ask">{t("settings.sortModeAsk")}</option>
            <option value="auto">{t("settings.sortModeAuto")}</option>
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">{t("settings.renameModeTitle")}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("settings.renameModeDescription")}</p>
          <select
            value={renameMode}
            onChange={(e) => handleSaveRenameMode(e.target.value)}
            className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
          >
            <option value="ask">{t("settings.renameModeAsk")}</option>
            <option value="auto">{t("settings.renameModeAuto")}</option>
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-sm font-medium">{t("settings.repairScanTitle")}</p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            {t("settings.repairScanDescription")}
          </p>
          <Button size="sm" variant="outline" onClick={() => repairScan.mutate()} disabled={repairScan.isPending}>
            {repairScan.isPending ? t("settings.repairScanRunning") : t("settings.repairScanButton")}
          </Button>
          {repairScan.isSuccess && (
            <ul className="space-y-0.5 text-xs text-[hsl(var(--muted-foreground))]">
              <li className="text-emerald-600">
                {t("settings.repairScanDone", { count: repairScan.data.checked })}
              </li>
              <li>{t("settings.repairTitles", { count: repairScan.data.titles_backfilled })}</li>
              <li>{t("settings.repairRenamedTitles", { count: repairScan.data.titles_changed })}</li>
              <li>{t("settings.repairEpisodes", { count: repairScan.data.episode_numbers_fixed })}</li>
              <li>{t("settings.repairMetadata", { count: repairScan.data.metadata_filled })}</li>
              <li>
                {t("settings.repairExpected", { count: repairScan.data.expected_episodes_added })}
              </li>
              <li>{t("settings.repairPosters", { count: repairScan.data.posters_relinked })}</li>
              {repairScan.data.without_local_source > 0 && (
                <li className="text-amber-600 dark:text-amber-400">
                  {t("settings.repairUnrepairable", {
                    count: repairScan.data.without_local_source,
                  })}
                </li>
              )}
            </ul>
          )}
          {repairScan.isError && <p className="text-xs text-red-500">{t("settings.repairScanFailed")}</p>}
        </CardContent>
      </Card>
    </div>
  )
}
