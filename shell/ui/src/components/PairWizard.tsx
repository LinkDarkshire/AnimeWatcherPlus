import { useEffect, useState } from "react"
import { shell, type ServerProbe } from "@/api/shell"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"
import { parsePairingQr, type PairingQr } from "@/lib/pairingQr"

const POLL_MS = 2000
const muted = "text-xs text-[hsl(var(--muted-foreground))]"

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** Scans the pairing QR code with the camera (phones only). */
async function scanPairingQr(): Promise<PairingQr | null> {
  const scanner = await import("@tauri-apps/plugin-barcode-scanner")
  let permission = await scanner.checkPermissions()
  if (permission !== "granted") permission = await scanner.requestPermissions()
  if (permission !== "granted") throw new Error("camera")
  const result = await scanner.scan({ windowed: false, formats: [scanner.Format.QRCode] })
  return parsePairingQr(result.content)
}

/** Pairing with a server, step by step: find it in the LAN, enter (or scan)
 * the code, wait for an admin's approval if needed. */
export function PairWizard({ onDone, canScan = false }: { onDone: () => void; canScan?: boolean }) {
  const t = useT()
  const [address, setAddress] = useState("")
  const [probe, setProbe] = useState<ServerProbe | null>(null)
  const [deviceName, setDeviceName] = useState(() =>
    canScan ? t("dataSource.defaultPhoneName") : t("dataSource.defaultDeviceName"),
  )
  const [code, setCode] = useState("")
  const [fingerprint, setFingerprint] = useState<string | null>(null)
  const [paired, setPaired] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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

  const scan = () =>
    run(async () => {
      let qr: PairingQr | null
      try {
        qr = await scanPairingQr()
      } catch {
        throw new Error(t("dataSource.cameraDenied"))
      }
      if (!qr) throw new Error(t("dataSource.qrInvalid"))
      setAddress(qr.server)
      setCode(qr.code)
      const found = await shell.probe(qr.server)
      if (qr.cert && qr.cert !== found.tls_fingerprint) throw new Error(t("dataSource.certMismatch"))
      setProbe(found)
    })

  const pair = () =>
    run(async () => {
      if (!probe) return
      const status = await shell.pair({
        lanUrl: probe.lan_url,
        pairingUrl: probe.pairing_url,
        serverName: probe.server_name,
        tlsFingerprint: probe.tls_fingerprint,
        deviceName: deviceName.trim(),
        code,
        setup: probe.setup_required,
      })
      if (status.status === "paired") setPaired(true)
      else setFingerprint(status.fingerprint)
    })

  return (
    <div className="space-y-3">
      {!probe && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault()
            search()
          }}
        >
          {canScan && (
            <>
              <Button type="button" className="w-full" disabled={busy} onClick={scan}>
                {t("dataSource.scanQr")}
              </Button>
              <p className={muted}>{t("dataSource.scanQrHint")}</p>
            </>
          )}
          <label className="block space-y-1 text-sm">
            <span>{t("dataSource.serverAddress")}</span>
            <Input
              autoFocus={!canScan}
              value={address}
              placeholder="192.168.1.10"
              onChange={(e) => setAddress(e.target.value)}
            />
          </label>
          <p className={muted}>{t("dataSource.serverAddressHint")}</p>
          <Button size="sm" type="submit" variant={canScan ? "outline" : "default"} disabled={busy || !address.trim()}>
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
          <p className="text-sm">{t("dataSource.found", { name: probe.server_name, version: probe.version })}</p>
          <label className="block space-y-1 text-sm">
            <span>{t("dataSource.deviceName")}</span>
            <Input value={deviceName} maxLength={60} onChange={(e) => setDeviceName(e.target.value)} />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{probe.setup_required ? t("dataSource.setupCode") : t("dataSource.pairingCode")}</span>
            <Input autoFocus value={code} className="font-mono uppercase" onChange={(e) => setCode(e.target.value)} />
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
          {!canScan && <p className={muted}>{t("dataSource.pairedNext")}</p>}
          <Button size="sm" onClick={onDone}>
            {canScan ? t("dataSource.openLibrary") : t("downloads.close")}
          </Button>
        </div>
      )}

      {error && <p className="text-sm text-red-500">{error}</p>}
    </div>
  )
}
