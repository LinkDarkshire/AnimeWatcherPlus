import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, ApiError } from "@/api/client"
import {
  restartApp,
  shell,
  type ImportResult,
  type PathMapping,
  type ServerConfig,
  type ServerProbe,
  type ShellConnection,
  useMe,
  useShellConnection,
} from "@/api/shell"
import type { Folder } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

const POLL_MS = 2000

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

const muted = "text-xs text-[hsl(var(--muted-foreground))]"

/** Where the library lives -- on this PC or on a server -- with pairing,
 * moving the library and switching. Desktop app only. */
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
      if (connection?.mode === "server") await restartApp()
    },
    onSettled: refresh,
  })

  if (!shell.available() || !connection) return null
  const server = connection.server
  const restartPending = connection.mode !== connection.next_mode

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
          {connection.mode === "server" && (
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

// --- Pairing ------------------------------------------------------------------------

function PairDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT()
  const [address, setAddress] = useState("")
  const [probe, setProbe] = useState<ServerProbe | null>(null)
  const [deviceName, setDeviceName] = useState("")
  const [code, setCode] = useState("")
  const [fingerprint, setFingerprint] = useState<string | null>(null)
  const [paired, setPaired] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setAddress("")
    setProbe(null)
    setDeviceName(t("dataSource.defaultDeviceName"))
    setCode("")
    setFingerprint(null)
    setPaired(false)
    setError(null)
  }, [open, t])

  // Waiting for an admin to approve this device.
  useEffect(() => {
    if (!fingerprint || paired) return
    const timer = setInterval(async () => {
      try {
        const status = await shell.pairStatus()
        if (status.status === "paired") setPaired(true)
        if (status.status === "rejected") {
          setFingerprint(null)
          setError(t("dataSource.pairRejected"))
        }
      } catch (e) {
        setFingerprint(null)
        setError(errorMessage(e))
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [fingerprint, paired, t])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const search = () => run(async () => setProbe(await shell.probe(address)))

  const pair = () =>
    run(async () => {
      if (!probe) return
      const status = await shell.pair({
        lanUrl: probe.lan_url,
        pairingUrl: probe.pairing_url,
        serverName: probe.server_name,
        deviceName: deviceName.trim(),
        code,
        setup: probe.setup_required,
      })
      if (status.status === "paired") setPaired(true)
      else setFingerprint(status.fingerprint)
    })

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("dataSource.pairTitle")}</DialogTitle>
          <DialogDescription>{t("dataSource.pairDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {!probe && (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault()
                search()
              }}
            >
              <label className="block space-y-1 text-sm">
                <span>{t("dataSource.serverAddress")}</span>
                <Input
                  autoFocus
                  value={address}
                  placeholder="192.168.1.10"
                  onChange={(e) => setAddress(e.target.value)}
                />
              </label>
              <p className={muted}>{t("dataSource.serverAddressHint")}</p>
              <Button size="sm" type="submit" disabled={busy || !address.trim()}>
                {busy ? t("dataSource.searching") : t("dataSource.search")}
              </Button>
            </form>
          )}

          {probe && !fingerprint && !paired && (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault()
                pair()
              }}
            >
              <p className="text-sm">
                {t("dataSource.found", { name: probe.server_name, version: probe.version })}
              </p>
              <label className="block space-y-1 text-sm">
                <span>{t("dataSource.deviceName")}</span>
                <Input value={deviceName} maxLength={60} onChange={(e) => setDeviceName(e.target.value)} />
              </label>
              <label className="block space-y-1 text-sm">
                <span>{probe.setup_required ? t("dataSource.setupCode") : t("dataSource.pairingCode")}</span>
                <Input
                  autoFocus
                  value={code}
                  className="font-mono uppercase"
                  onChange={(e) => setCode(e.target.value)}
                />
              </label>
              <p className={muted}>
                {probe.setup_required ? t("dataSource.setupCodeHint") : t("dataSource.pairingCodeHint")}
              </p>
              <div className="flex gap-2">
                <Button size="sm" type="submit" disabled={busy || !code.trim() || !deviceName.trim()}>
                  {t("dataSource.pair")}
                </Button>
                <Button size="sm" type="button" variant="ghost" onClick={() => setProbe(null)}>
                  {t("common.previous")}
                </Button>
              </div>
            </form>
          )}

          {fingerprint && !paired && (
            <div className="space-y-2">
              <p className="text-sm">{t("dataSource.waitingForApproval")}</p>
              <p className="text-center font-mono text-lg tracking-wider">{fingerprint}</p>
              <p className={muted}>{t("dataSource.compareFingerprint")}</p>
            </div>
          )}

          {paired && (
            <div className="space-y-2">
              <p className="text-sm text-emerald-600">{t("dataSource.paired")}</p>
              <p className={muted}>{t("dataSource.pairedNext")}</p>
              <Button size="sm" onClick={onClose}>
                {t("downloads.close")}
              </Button>
            </div>
          )}

          {error && <p className="text-sm text-red-500">{error}</p>}
        </div>
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
      <DialogContent className="max-w-lg">
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
      <DialogContent className="max-w-lg">
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
