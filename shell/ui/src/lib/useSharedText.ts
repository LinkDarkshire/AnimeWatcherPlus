import { useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { shell } from "@/api/shell"

/** Phones: text shared to the app (e.g. a post from X) opens the wishlist
 * with suggestions. Checked on start and whenever the app comes back to the
 * foreground, which is what sharing to an already running app does. */
export function useSharedText(enabled: boolean) {
  const navigate = useNavigate()

  useEffect(() => {
    if (!enabled) return
    const check = async () => {
      if (document.visibilityState !== "visible") return
      const text = await shell.takeSharedText().catch(() => null)
      if (text) navigate("/wishlist", { state: { shared: text } })
    }
    check()
    document.addEventListener("visibilitychange", check)
    window.addEventListener("focus", check)
    return () => {
      document.removeEventListener("visibilitychange", check)
      window.removeEventListener("focus", check)
    }
  }, [enabled, navigate])
}
