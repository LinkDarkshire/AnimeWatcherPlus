import { useEffect, useState } from "react"
import type { Update } from "@tauri-apps/plugin-updater"
import { isTauri } from "@/api/client"
import { Button } from "@/components/ui/button"

type UpdateState =
  | { status: "idle" }
  | { status: "available"; version: string }
  | { status: "downloading" }
  | { status: "error"; message: string }

/** Checks GitHub Releases (see tauri.conf.json's plugins.updater.endpoints)
 * once on startup; only ever active inside the Tauri desktop shell -- there
 * is no browser-dev-mode equivalent. */
export function UpdateBanner() {
  const [state, setState] = useState<UpdateState>({ status: "idle" })
  const [update, setUpdate] = useState<Update | null>(null)

  useEffect(() => {
    if (!isTauri()) return
    let cancelled = false
    void (async () => {
      const { check } = await import("@tauri-apps/plugin-updater")
      try {
        const result = await check()
        if (cancelled || !result) return
        setUpdate(result)
        setState({ status: "available", version: result.version })
      } catch {
        // No network / GitHub unreachable -- silently stay on "idle", must
        // never block normal app usage.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (state.status === "idle") return null

  const handleInstall = async () => {
    if (!update) return
    setState({ status: "downloading" })
    try {
      await update.downloadAndInstall()
      const { relaunch } = await import("@tauri-apps/plugin-process")
      await relaunch()
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : "Update fehlgeschlagen" })
    }
  }

  return (
    <div className="border-b border-sky-300 bg-sky-50 px-4 py-2 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200">
      {state.status === "available" && (
        <div className="flex items-center justify-between gap-4">
          <span>Update auf Version {state.version} verfügbar.</span>
          <Button size="sm" onClick={handleInstall}>
            Jetzt installieren & neu starten
          </Button>
        </div>
      )}
      {state.status === "downloading" && <span>Update wird heruntergeladen und installiert…</span>}
      {state.status === "error" && (
        <span className="text-red-600 dark:text-red-400">Update fehlgeschlagen: {state.message}</span>
      )}
    </div>
  )
}
