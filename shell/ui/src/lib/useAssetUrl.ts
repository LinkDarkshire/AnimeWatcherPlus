import { useEffect, useState } from "react"
import { resolveAssetUrl } from "@/api/client"

/** Resolves a server-relative asset path (e.g. an anime's poster_path)
 * against the Core's actual base URL, which is only known asynchronously
 * (Tauri sidecar port, or the dev-mode .env value). Returns undefined until
 * resolved or when there's no path to resolve.
 */
export function useAssetUrl(path: string | null | undefined): string | undefined {
  const [url, setUrl] = useState<string | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    if (!path) {
      setUrl(undefined)
      return
    }
    resolveAssetUrl(path).then((resolved) => {
      if (!cancelled) setUrl(resolved)
    })
    return () => {
      cancelled = true
    }
  }, [path])

  return url
}
