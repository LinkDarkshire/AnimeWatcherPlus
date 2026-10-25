import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, ApiError } from "@/api/client"
import {
  restartApp,
  shell,
  type ImportResult,
  type PathMapping,
  type ServerConfig,
  type ShellConnection,
  useMe,
  useShellConnection,
} from "@/api/shell"
import type { Folder } from "@/api/types"
import type { FolderMapping } from "@/lib/folderMapping"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { PairWizard } from "@/components/PairWizard"
import { useT } from "@/i18n/I18nContext"

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

const muted = "text-xs text-[hsl(var(--muted-foreground))]"

/** Where the library lives -- on this PC or on a server -- with pairing,
 * moving the library and switching. In the app only; on a phone just the
 * server's addresses and removing the pairing. */
export function DataSourceSection() {
  const t = useT()
  const queryClient = useQueryClient()
  const { data: connection } = useShellConnection()
  const [dialog, setDialog] = useState<null | "pair" | "push" | "leave">(null)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["shell-connection"] })

  const switchToServer = useMutation({
    mutationFn: async () => {
      await shell.switchMode("server")
      await restartApp()
    },
  })
  const forget = useMutation({
    mutationFn: async () => {
      await shell.forget()
      // A phone goes back to its pairing screen.
      if (connection?.platform === "mobile") window.location.reload()
      else if (connection?.mode === "server") await restartApp()
    },
    onSettled: refresh,
  })

  if (!shell.available() || !connection) return null
  const server = connection.server
  const mobile = connection.platform === "mobile"
  const restartPending = !mobile && connection.mode !== connection.next_mode

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <p className="text-sm font-medium">{t("dataSource.title")}</p>
        <p className={muted}>
          {connection.mode === "server"
            ? t("dataSource.onServer", { name: server?.name ?? "" })
            : t("dataSource.local")}
        </p>

        {server && <ServerDetails server={server} onSaved={refresh} />}
        {server && connection.mode === "server" && !mobile && (
          <FolderMappingsEditor server={server} onSaved={refresh} />
        )}

        {restartPending && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
            {t("dataSource.restartPending")}
            <Button size="sm" variant="outline" onClick={() => restartApp()}>
              {t("dataSource.restartNow")}
            </Button>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {connection.mode === "local" && !server && (
            <Button size="sm" onClick={() => setDialog("pair")}>
              {t("dataSource.connect")}
            </Button>
          )}
          {connection.mode === "local" && server && (
            <>
              <Button size="sm" variant="outline" onClick={() => setDialog("push")}>
                {t("dataSource.push")}
              </Button>
              {connection.next_mode === "local" && (
                <Button
                  size="sm"
                  disabled={switchToServer.isPending}
                  onClick={() => {
                    if (confirm(t("dataSource.switchToServerConfirm", { name: server.name }))) switchToServer.mutate()
                  }}
                >
                  {t("dataSource.switchToServer")}
                </Button>
              )}
            </>
          )}
          {connection.mode === "server" && !mobile && (
            <Button size="sm" variant="outline" onClick={() => setDialog("leave")}>
              {t("dataSource.backToLocal")}
            </Button>
          )}
          {server && (
            <Button
              size="sm"
              variant="ghost"
              disabled={forget.isPending}
              onClick={() => {
                if (confirm(t("dataSource.forgetConfirm", { name: server.name }))) forget.mutate()
              }}
            >
              {t("dataSource.forget")}
            </Button>
          )}
        </div>
      </CardContent>

      <PairDialog
        open={dialog === "pair"}
        onClose={() => {
          setDialog(null)
          refresh()
        }}
      />
      {server && (
        <PushDialog open={dialog === "push"} server={server} onClose={() => setDialog(null)} />
      )}
      {server && connection.mode === "server" && (
        <LeaveDialog open={dialog === "leave"} connection={connection} onClose={() => setDialog(null)} />
      )}
    </Card>
  )
}

function ServerDetails({ server, onSaved }: { server: ServerConfig; onSaved: () => void }) {
  const t = useT()
  const [internetUrl, setInternetUrl] = useState(server.internet_url ?? "")
  useEffect(() => setInternetUrl(server.internet_url ?? ""), [server.internet_url])

  const save = useMutation({
    mutationFn: () => shell.setInternetUrl(internetUrl.trim() || null),
    onSuccess: onSaved,
    meta: { showsOwnError: true },
  })

  return (
    <div className="space-y-2 rounded-md border border-[hsl(var(--border))] p-3">
      <p className="text-xs">
        {t("dataSource.lanAddress")}: <span className="font-mono">{server.lan_url}</span>
      </p>
      <label className="block space-y-1 text-xs">
        <span>{t("dataSource.internetAddress")}</span>
        <div className="flex gap-2">
          <Input
            value={internetUrl}
            placeholder="https://anime.example.com"
            onChange={(e) => setInternetUrl(e.target.value)}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={save.isPending || internetUrl.trim() === (server.internet_url ?? "")}
            onClick={() => save.mutate()}
          >
            {t("common.save")}
          </Button>
        </div>
      </label>
      <p className={muted}>{t("dataSource.internetHint")}</p>
      {save.isError && <p className="text-xs text-red-500">{errorMessage(save.error)}</p>}
    </div>
  )
}

/** How this PC reaches the server's folders (e.g. over SMB), so "open
 * folder" works for anime and the plugins folder with a server too. */
function FolderMappingsEditor({ server, onSaved }: { server: ServerConfig; onSaved: () => void }) {
  const t = useT()
  const [rows, setRows] = useState<FolderMapping[]>(server.folder_mappings ?? [])
  useEffect(() => setRows(server.folder_mappings ?? []), [server.folder_mappings])
  const folders = useFolders(true)
  // Suggestions: the server's library folders and its data folder (plugins).
  const suggestions = [...new Set([...(folders.data ?? []).map((f) => f.path), "/data"])]

  const save = useMutation({
    mutationFn: () => shell.setFolderMappings(rows.filter((r) => r.server.trim() && r.local.trim())),
    onSuccess: onSaved,
    meta: { showsOwnError: true },
  })
  const update = (index: number, change: Partial<FolderMapping>) =>
    setRows(rows.map((row, i) => (i === index ? { ...row, ...change } : row)))

  return (
    <div className="space-y-2 rounded-md border border-[hsl(var(--border))] p-3">
      <p className="text-xs font-medium">{t("dataSource.folderMappingsTitle")}</p>
      <p className={muted}>{t("dataSource.folderMappingsHint")}</p>
      <datalist id="server-folder-suggestions">
        {suggestions.map((path) => (
          <option key={path} value={path} />
        ))}
      </datalist>
      {rows.map((row, index) => (
        <div key={index} className="flex flex-col gap-1 sm:flex-row sm:items-center">
          <Input
            list="server-folder-suggestions"
            value={row.server}
            placeholder="/media/Anime"
            className="font-mono text-xs"
            onChange={(e) => update(index, { server: e.target.value })}
          />
          <span className="hidden text-xs sm:inline">→</span>
          <Input
            value={row.local}
            placeholder={navigator.userAgent.includes("Windows") ? "\\\\nas\\anime" : "smb://nas/anime"}
            className="font-mono text-xs"
            onChange={(e) => update(index, { local: e.target.value })}
          />
          <Button size="sm" variant="ghost" onClick={() => setRows(rows.filter((_, i) => i !== index))}>
            ✕
          </Button>
        </div>
      ))}
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => setRows([...rows, { server: "", local: "" }])}>
          {t("dataSource.folderMappingsAdd")}
        </Button>
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("common.save")}
        </Button>
      </div>
      {save.isSuccess && <p className="text-xs text-emerald-600">{t("common.saved")}</p>}
      {save.isError && <p className="text-xs text-red-500">{errorMessage(save.error)}</p>}
    </div>
  )
}

// --- Pairing ------------------------------------------------------------------------

function PairDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT()
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{t("dataSource.pairTitle")}</DialogTitle>
          <DialogDescription>{t("dataSource.pairDescription")}</DialogDescription>
        </DialogHeader>
        {/* Remounted on every open: starts from the first step. */}
        {open && <PairWizard onDone={onClose} />}
      </DialogContent>
    </Dialog>
  )
}

// --- Moving the library -------------------------------------------------------------

/** One target path per library folder; empty means unchanged. */
function PathMappingFields({
  folders,
  targets,
  onChange,
  placeholder,
}: {
  folders: Folder[]
  targets: Record<number, string>
  onChange: (targets: Record<number, string>) => void
  placeholder: string
}) {
  return (
    <div className="max-h-64 space-y-2 overflow-y-auto">
      {folders.map((folder) => (
        <div key={folder.id} className="space-y-1">
          <p className="truncate font-mono text-xs" title={folder.path}>
            {folder.path}
          </p>
          <Input
            value={targets[folder.id] ?? ""}
            placeholder={placeholder}
            onChange={(e) => onChange({ ...targets, [folder.id]: e.target.value })}
          />
        </div>
      ))}
    </div>
  )
}

function mappingsFor(folders: Folder[] | undefined, targets: Record<number, string>): PathMapping[] {
  return (folders ?? []).flatMap((folder) => {
    const target = targets[folder.id]?.trim()
    return target && target !== folder.path ? [{ source: folder.path, target }] : []
  })
}

function useFolders(enabled: boolean) {
  return useQuery({
    queryKey: ["folders"],
    queryFn: () => api.get<Folder[]>("/api/v1/folders"),
    enabled,
  })
}

/** Local -> server. */
function PushDialog({ open, server, onClose }: { open: boolean; server: ServerConfig; onClose: () => void }) {
  const t = useT()
  const folders = useFolders(open)
  const [targets, setTargets] = useState<Record<number, string>>({})
  const [needsForce, setNeedsForce] = useState(false)
  const [force, setForce] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setTargets({})
    setNeedsForce(false)
    setForce(false)
    setResult(null)
    setError(null)
  }, [open])

  const push = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await shell.pushLibrary(mappingsFor(folders.data, targets), force))
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setNeedsForce(true)
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const switchNow = async () => {
    try {
      await shell.switchMode("server")
      await restartApp()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && onClose()}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{t("dataSource.pushTitle", { name: server.name })}</DialogTitle>
          <DialogDescription>{t("dataSource.pushDescription")}</DialogDescription>
        </DialogHeader>

        {!result && (
          <div className="space-y-3">
            <p className="text-sm">{t("dataSource.mappingServerHint")}</p>
            {folders.data && (
              <PathMappingFields
                folders={folders.data}
                targets={targets}
                onChange={setTargets}
                placeholder={t("dataSource.mappingServerPlaceholder")}
              />
            )}
            {needsForce && (
              <label className="flex items-start gap-2 text-sm text-amber-600 dark:text-amber-400">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                {t("dataSource.pushForce")}
              </label>
            )}
            <Button size="sm" disabled={busy || (needsForce && !force)} onClick={push}>
              {busy ? t("dataSource.transferring") : t("dataSource.pushStart")}
            </Button>
          </div>
        )}

        {result && (
          <div className="space-y-2 text-sm">
            <p className="text-emerald-600">
              {t("dataSource.pushDone", { rows: result.rows, plugins: result.plugins })}
            </p>
            {result.unmapped_folders.length > 0 && (
              <div className="text-xs text-amber-600 dark:text-amber-400">
                <p>{t("dataSource.unmappedFolders")}</p>
                <ul className="list-inside list-disc font-mono">
                  {result.unmapped_folders.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex gap-2">
              <Button size="sm" onClick={switchNow}>
                {t("dataSource.switchToServer")}
              </Button>
              <Button size="sm" variant="ghost" onClick={onClose}>
                {t("downloads.close")}
              </Button>
            </div>
          </div>
        )}

        {error && <p className="mt-2 text-sm text-red-500">{error}</p>}
      </DialogContent>
    </Dialog>
  )
}

/** Server -> local, optionally taking the library along. */
function LeaveDialog({
  open,
  connection,
  onClose,
}: {
  open: boolean
  connection: ShellConnection
  onClose: () => void
}) {
  const t = useT()
  const me = useMe(open)
  const isAdmin = me.data?.is_admin ?? false
  const [takeLibrary, setTakeLibrary] = useState(false)
  const folders = useFolders(open && takeLibrary)
  const [targets, setTargets] = useState<Record<number, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setTakeLibrary(false)
    setTargets({})
    setError(null)
  }, [open])

  const leave = async () => {
    setBusy(true)
    setError(null)
    try {
      if (takeLibrary) await shell.pullLibrary(mappingsFor(folders.data, targets))
      await shell.switchMode("local")
      await restartApp()
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && onClose()}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{t("dataSource.leaveTitle")}</DialogTitle>
          <DialogDescription>
            {t("dataSource.leaveDescription", { name: connection.server?.name ?? "" })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={takeLibrary}
              disabled={!isAdmin}
              onChange={(e) => setTakeLibrary(e.target.checked)}
            />
            <span>
              {t("dataSource.takeLibrary")}
              {!isAdmin && <span className={`block ${muted}`}>{t("dataSource.adminOnly")}</span>}
            </span>
          </label>
          {takeLibrary && (
            <>
              <p className="text-xs text-amber-600 dark:text-amber-400">{t("dataSource.takeLibraryWarning")}</p>
              <p className="text-sm">{t("dataSource.mappingLocalHint")}</p>
              {folders.data && (
                <PathMappingFields
                  folders={folders.data}
                  targets={targets}
                  onChange={setTargets}
                  placeholder={t("dataSource.mappingLocalPlaceholder")}
                />
              )}
            </>
          )}
          <Button size="sm" disabled={busy || (takeLibrary && !folders.data)} onClick={leave}>
            {busy ? t("dataSource.transferring") : t("dataSource.leaveStart")}
          </Button>
          {error && <p className="text-sm text-red-500">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  )
}
