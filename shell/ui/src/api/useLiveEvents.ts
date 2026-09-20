import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { wsUrl } from "./client"
import { invalidateServerQueries } from "./hooks"
import type { EmptyDirEntry, WsEvent } from "./types"

const RECONNECT_DELAY_MS = 3000

/** A full library scan emits one event per anime, back to back. Invalidating
 * per event turns that into hundreds of refetches of the same few queries --
 * including the pending-actions count, which has to walk the library. Batching
 * the keys and flushing them on a trailing timer collapses a whole burst into
 * one refetch per affected query, while a lone event still lands within this
 * window. */
const INVALIDATE_DEBOUNCE_MS = 700

/** Subscribes to the Core's WS event stream and invalidates the relevant
 * TanStack Query caches so the UI reflects scan/identify/sort progress live
 * (Kap. 7.2). Reconnects automatically if the sidecar restarts.
 */
export function useLiveEvents() {
  const queryClient = useQueryClient()

  useEffect(() => {
    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let cancelled = false
    let connectedBefore = false

    const pendingKeys = new Set<string>()
    let flushTimer: ReturnType<typeof setTimeout> | null = null

    const invalidate = (...keys: string[]) => {
      for (const key of keys) pendingKeys.add(key)
      if (flushTimer) return
      flushTimer = setTimeout(() => {
        flushTimer = null
        const keysToFlush = [...pendingKeys]
        pendingKeys.clear()
        for (const key of keysToFlush) queryClient.invalidateQueries({ queryKey: [key] })
      }, INVALIDATE_DEBOUNCE_MS)
    }

    const connect = async () => {
      const url = await wsUrl()
      if (cancelled) return
      socket = new WebSocket(url)

      socket.onopen = () => {
        // The core is reachable (again). A query that failed while it wasn't
        // -- e.g. the library's first load during a slow core start, when the
        // NAS or a VPN held startup up -- would otherwise stay on its error
        // message for good, since nothing else refetches a failed query.
        // After a reconnect everything may be stale (the core restarted).
        invalidateServerQueries(queryClient, !connectedBefore)
        connectedBefore = true
      }

      socket.onmessage = (message) => {
        let payload: WsEvent
        try {
          payload = JSON.parse(message.data)
        } catch {
          return
        }
        handleEvent(payload)
      }

      socket.onclose = () => {
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }
    }

    const handleEvent = (payload: WsEvent) => {
      switch (payload.event) {
        case "anime.discovered":
        case "anime.identified":
        case "anime.needs_review":
          invalidate(
            "animes",
            "review-queue",
            "sort-queue",
            "rename-queue",
            "pending-actions-count",
            // A scan or identification changes which episodes are expected
            // and which files are present, i.e. the soll/ist comparison.
            "missing-episodes",
            "missing-episodes-overview",
            "local-episodes",
            "anime-pending-actions",
          )
          break
        case "anime.duplicate_detected":
          invalidate("duplicates", "pending-actions-count")
          break
        case "anime.sorted":
          invalidate(
            "animes",
            "review-queue",
            "sort-queue",
            "rename-queue",
            "folders",
            "pending-actions-count",
            "missing-episodes",
            "missing-episodes-overview",
            "local-episodes",
            "anime",
            "anime-pending-actions",
          )
          break
        case "anime.renamed":
          invalidate(
            "animes",
            "anime",
            "rename-queue",
            "pending-actions-count",
            "local-episodes",
            "anime-pending-actions",
          )
          break
        case "anime.titles_resynced":
          // The startup backfill rewrote display titles, which also decide
          // what counts as misnamed on disk.
          invalidate(
            "animes",
            "anime",
            "rename-queue",
            "pending-actions-count",
            "missing-episodes-overview",
            "anime-pending-actions",
          )
          break
        case "anime.removed":
          invalidate(
            "animes",
            "review-queue",
            "duplicates",
            "sort-queue",
            "rename-queue",
            "pending-actions-count",
            "missing-episodes-overview",
          )
          break
        case "folder.empty_dir_found": {
          const entry = payload.data as EmptyDirEntry
          queryClient.setQueryData<EmptyDirEntry[]>(["pending-empty-dirs"], (old = []) =>
            old.some((e) => e.path === entry.path) ? old : [...old, entry]
          )
          break
        }
        case "library.repaired":
          // A repair pass can have changed titles, numbers and artwork across
          // the whole library at once.
          invalidateServerQueries(queryClient)
          break
        case "scan.progress":
          invalidate("folders")
          break
        default:
          break
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (flushTimer) clearTimeout(flushTimer)
      socket?.close()
    }
  }, [queryClient])
}
