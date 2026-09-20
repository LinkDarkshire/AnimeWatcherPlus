import { useEffect, useState, type ReactNode } from "react"
import type { Update } from "@tauri-apps/plugin-updater"
import { isTauri } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useT } from "@/i18n/I18nContext"

const CHECK_TIMEOUT_MS = 5000

type GateState =
  | { status: "checking" }
  | { status: "ready" }
  | { status: "prompt"; update: Update }
  | { status: "installing"; update: Update }
  | { status: "install-failed"; update: Update; message: string }

/** Checks for an update before the app renders anything else, per user
 * request -- not a passive banner discovered after the fact. A stale
 * install (e.g. 0.1.0 sitting around for weeks) should be caught right at
 * launch, not left for the user to notice on their own. Only ever active
 * inside the Tauri desktop shell; browser dev mode always renders straight
 * through. A slow/unreachable GitHub is never allowed to block startup for
 * more than CHECK_TIMEOUT_MS -- current version or timeout both fall
 * through to the app starting normally. */
export function UpdateGate({ children }: { children: ReactNode }) {
  const t = useT()
  const [state, setState] = useState<GateState>(isTauri() ? { status: "checking" } : { status: "ready" })

  useEffect(() => {
    if (!isTauri()) return
    let cancelled = false

    void (async () => {
      try {
        const { check } = await import("@tauri-apps/plugin-updater")
        const timeout = new Promise<null>((resolve) => setTimeout(() => resolve(null), CHECK_TIMEOUT_MS))
        const result = await Promise.race([check({ timeout: CHECK_TIMEOUT_MS }), timeout])
        if (cancelled) return
        setState(result ? { status: "prompt", update: result } : { status: "ready" })
      } catch {
        // Offline / GitHub unreachable / malformed manifest -- never block
        // the app over this, just continue as if there's no update.
        if (!cancelled) setState({ status: "ready" })
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  const handleInstall = async (update: Update) => {
    setState({ status: "installing", update })
    try {
      await update.downloadAndInstall()
      const { relaunch } = await import("@tauri-apps/plugin-process")
      await relaunch()
    } catch (err) {
      setState({ status: "install-failed", update, message: err instanceof Error ? err.message : String(err) })
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
    const { update } = state
    const installing = state.status === "installing"
    return (
      <Dialog open>
        <DialogContent onEscapeKeyDown={(e) => e.preventDefault()} onPointerDownOutside={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>{t("updateGate.title")}</DialogTitle>
            <DialogDescription>
              {installing ? t("updateGate.installing") : t("updateGate.available", { version: update.version })}
            </DialogDescription>
          </DialogHeader>
          {state.status === "install-failed" && (
            <p className="text-sm text-red-500">{t("updateGate.installFailed", { message: state.message })}</p>
          )}
          {!installing && (
            <DialogFooter>
              <Button variant="ghost" onClick={() => setState({ status: "ready" })}>
                {t("updateGate.skip")}
              </Button>
              <Button onClick={() => void handleInstall(update)}>{t("updateGate.install")}</Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    )
  }

  return <>{children}</>
}
