import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import { shell, useMe, useShellConnection, type Device, type JoinRequest, type PairingCode } from "@/api/shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useT } from "@/i18n/I18nContext"
import { pairingQrText } from "@/lib/pairingQr"

const POLL_MS = 2000
const muted = "text-xs text-[hsl(var(--muted-foreground))]"

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** The devices paired with the server: list, revoke, add. Admin devices
 * only, while the library is on a server. */
export function DevicesSection() {
  const t = useT()
  const queryClient = useQueryClient()
  const { data: connection } = useShellConnection()
  const onServer = connection?.mode === "server"
  const me = useMe(onServer)
  const isAdmin = onServer && (me.data?.is_admin ?? false)
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api.get<Device[]>("/api/v1/devices"),
    enabled: isAdmin,
  })
  const revoke = useMutation({
    mutationFn: (id: number) => api.del<void>(`/api/v1/devices/${id}`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["devices"] }),
  })
  const [adding, setAdding] = useState(false)

  if (!isAdmin) return null

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <p className="text-sm font-medium">{t("devices.title")}</p>
        <p className={muted}>{t("devices.description")}</p>
        <ul className="divide-y divide-[hsl(var(--border))]">
          {devices.data?.map((device) => (
            <li key={device.id} className="flex items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <p className={`text-sm ${device.revoked ? "line-through opacity-60" : ""}`}>
                  {device.name}
                  {device.id === me.data?.device_id && <span className={`ml-2 ${muted}`}>{t("devices.thisDevice")}</span>}
                </p>
                <p className={`font-mono ${muted}`}>{device.fingerprint}</p>
                <p className={muted}>
                  {device.revoked
                    ? t("devices.revoked")
                    : device.last_seen_at
                      ? t("devices.lastSeen", { date: new Date(device.last_seen_at).toLocaleString() })
                      : t("devices.neverSeen")}
                </p>
              </div>
              {device.is_admin && <Badge>{t("devices.admin")}</Badge>}
              {!device.revoked && device.id !== me.data?.device_id && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={revoke.isPending}
                  onClick={() => {
                    if (confirm(t("devices.revokeConfirm", { name: device.name }))) revoke.mutate(device.id)
                  }}
                >
                  {t("devices.revoke")}
                </Button>
              )}
            </li>
          ))}
        </ul>
        <Button size="sm" onClick={() => setAdding(true)}>
          {t("devices.add")}
        </Button>
      </CardContent>
      <AddDeviceDialog
        open={adding}
        onClose={() => {
          setAdding(false)
          queryClient.invalidateQueries({ queryKey: ["devices"] })
        }}
      />
    </Card>
  )
}

/** Shows a pairing code for the new device and the join requests coming
 * in, to approve after comparing fingerprints. */
function AddDeviceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT()
  const [code, setCode] = useState<PairingCode | null>(null)
  const [expiresAt, setExpiresAt] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const [requests, setRequests] = useState<JoinRequest[]>([])
  const [asAdmin, setAsAdmin] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<string | null>(null)

  const { data: connection } = useShellConnection()
  const lanUrl = connection?.server?.lan_url
  const [qr, setQr] = useState<string | null>(null)

  const newCode = async () => {
    setError(null)
    try {
      const created = await shell.pairingCall<PairingCode>("POST", "/pair/codes")
      setCode(created)
      setExpiresAt(Date.now() + created.expires_in * 1000)
      // For a phone to scan: the server's LAN address and the code.
      setQr(lanUrl ? await shell.qrSvg(pairingQrText(lanUrl, created.code)) : null)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  useEffect(() => {
    if (!open) return
    setCode(null)
    setQr(null)
    setRequests([])
    setAsAdmin({})
    newCode()
    const timer = setInterval(async () => {
      setNow(Date.now())
      try {
        setRequests(await shell.pairingCall<JoinRequest[]>("GET", "/pair/requests"))
      } catch {
        // Shown when making the code failed; nothing to add here.
      }
    }, POLL_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- newCode only uses setters
  }, [open])

  const decide = async (request: JoinRequest, approve: boolean) => {
    setError(null)
    try {
      await shell.pairingCall("POST", `/pair/requests/${encodeURIComponent(request.id)}`, {
        approve,
        admin: approve && (asAdmin[request.id] ?? false),
      })
      setRequests((current) => current.filter((r) => r.id !== request.id))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const secondsLeft = Math.max(0, Math.round((expiresAt - now) / 1000))

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{t("devices.addTitle")}</DialogTitle>
          <DialogDescription>{t("devices.addDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {code && (
            <div className="space-y-1 text-center">
              {qr && secondsLeft > 0 && (
                // SVG made by the app's own Rust side from the code above.
                <div
                  className="mx-auto w-56 rounded-md bg-white p-2 [&>svg]:h-auto [&>svg]:w-full"
                  dangerouslySetInnerHTML={{ __html: qr }}
                />
              )}
              <p className="font-mono text-2xl tracking-widest">{code.code}</p>
              <p className={muted}>
                {secondsLeft > 0
                  ? t("devices.codeValid", { minutes: Math.floor(secondsLeft / 60), seconds: String(secondsLeft % 60).padStart(2, "0") })
                  : t("devices.codeExpired")}
              </p>
              {secondsLeft === 0 && (
                <Button size="sm" variant="outline" onClick={newCode}>
                  {t("devices.newCode")}
                </Button>
              )}
            </div>
          )}

          <div className="space-y-2">
            <p className="text-sm font-medium">{t("devices.requests")}</p>
            {requests.length === 0 && <p className={muted}>{t("devices.noRequests")}</p>}
            {requests.map((request) => (
              <div key={request.id} className="space-y-2 rounded-md border border-[hsl(var(--border))] p-3">
                <p className="text-sm">{request.name}</p>
                <p className="font-mono text-sm">{request.fingerprint}</p>
                <p className={muted}>{t("devices.compareFingerprint")}</p>
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={asAdmin[request.id] ?? false}
                    onChange={(e) => setAsAdmin({ ...asAdmin, [request.id]: e.target.checked })}
                  />
                  {t("devices.makeAdmin")}
                </label>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => decide(request, true)}>
                    {t("devices.approve")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => decide(request, false)}>
                    {t("devices.reject")}
                  </Button>
                </div>
              </div>
            ))}
          </div>

          {error && <p className="text-sm text-red-500">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  )
}
