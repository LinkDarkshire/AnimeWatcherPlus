import { useEffect, useState, type ReactNode } from "react"
import { api, isTauri, openExternal } from "@/api/client"
import { shell, type Me } from "@/api/shell"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useT } from "@/i18n/I18nContext"
import { androidApkUrl, compareVersions } from "@/lib/version"

const CHECK_TIMEOUT_MS = 5000

/** What to update to. "latest": the newest release (the app with its own
 * data). "server": exactly the connected server's version -- updating the
 * server is enough, the apps follow when they connect. */
interface Offer {
  version: string
  target: "latest" | "server"
  platform: "desktop" | "mobile"
}

type GateState =
  | { status: "checking" }
  | { status: "ready" }
  | { status: "prompt"; offer: Offer }
  | { status: "installing"; offer: Offer }
  | { status: "install-failed"; offer: Offer; message: string }

function withTimeout<T>(promise: Promise<T>): Promise<T | null> {
  const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), CHECK_TIMEOUT_MS))
  return Promise.race([promise, timeout])
}

async function findOffer(): Promise<Offer | null> {
  const { invoke } = await import("@tauri-apps/api/core")
  const { getVersion } = await import("@tauri-apps/api/app")
  const connection = await shell.connection()
  const appVersion = await getVersion()

  if (connection.mode === "server" && connection.server) {
    const me = await withTimeout(api.get<Me>("/api/v1/auth/me"))
    if (!me || compareVersions(me.server_version, appVersion) <= 0) return null
    if (connection.platform === "mobile") {
      return { version: me.server_version, target: "server", platform: "mobile" }
    }
    const found = await withTimeout(invoke<string | null>("app_update_check", { version: me.server_version }))
    return found ? { version: found, target: "server", platform: "desktop" } : null
  }
  if (connection.platform !== "desktop") return null
  const found = await withTimeout(invoke<string | null>("app_update_check", { version: null }))
  return found ? { version: found, target: "latest", platform: "desktop" } : null
}

/** Checks for an update before the app renders anything else -- a stale
 * install should be caught right at launch. With a server, the app follows
 * the server's version (no newer, no older); on Android, where an app can't
 * install itself, it offers the matching APK. Only inside the app shell; an
 * unreachable GitHub or server never blocks startup for more than
 * CHECK_TIMEOUT_MS. */
export function UpdateGate({ children }: { children: ReactNode }) {
  const t = useT()
  const [state, setState] = useState<GateState>(isTauri() ? { status: "checking" } : { status: "ready" })

  useEffect(() => {
    if (!isTauri()) return
    let cancelled = false
    void (async () => {
      try {
        const offer = await findOffer()
        if (!cancelled) setState(offer ? { status: "prompt", offer } : { status: "ready" })
      } catch {
        // Offline / GitHub or server unreachable -- never block the app.
        if (!cancelled) setState({ status: "ready" })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleInstall = async (offer: Offer) => {
    if (offer.platform === "mobile") {
      await openExternal(androidApkUrl(offer.version))
      return
    }
    setState({ status: "installing", offer })
    try {
      const { invoke } = await import("@tauri-apps/api/core")
      // Restarts the app when done (on Windows the installer takes over).
      await invoke("app_update_install", { version: offer.target === "server" ? offer.version : null })
    } catch (err) {
      setState({ status: "install-failed", offer, message: err instanceof Error ? err.message : String(err) })
    }
  }

  if (state.status === "checking") {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
        {t("updateGate.checking")}
      </div>
    )
  }

  if (state.status === "prompt" || state.status === "installing" || state.status === "install-failed") {
    const { offer } = state
    const installing = state.status === "installing"
    const description = installing
      ? t("updateGate.installing")
      : offer.platform === "mobile"
        ? t("updateGate.androidAvailable", { version: offer.version })
        : offer.target === "server"
          ? t("updateGate.serverVersion", { version: offer.version })
          : t("updateGate.available", { version: offer.version })
    return (
      <Dialog open>
        <DialogContent onEscapeKeyDown={(e) => e.preventDefault()} onPointerDownOutside={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>{t("updateGate.title")}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {state.status === "install-failed" && (
            <p className="text-sm text-red-500">{t("updateGate.installFailed", { message: state.message })}</p>
          )}
          {!installing && (
            <DialogFooter>
              <Button variant="ghost" onClick={() => setState({ status: "ready" })}>
                {t("updateGate.skip")}
              </Button>
              <Button onClick={() => void handleInstall(offer)}>
                {offer.platform === "mobile" ? t("updateGate.downloadApk") : t("updateGate.install")}
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    )
  }

  return <>{children}</>
}
