import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { wsUrl } from "./client"
import type { WsEvent } from "./types"

const RECONNECT_DELAY_MS = 3000

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

    const connect = async () => {
      const url = await wsUrl()
      if (cancelled) return
      socket = new WebSocket(url)

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
        case "anime.missing_on_disk":
        case "anime.sorted":
          queryClient.invalidateQueries({ queryKey: ["animes"] })
          queryClient.invalidateQueries({ queryKey: ["review-queue"] })
          break
        case "scan.progress":
          queryClient.invalidateQueries({ queryKey: ["folders"] })
          break
        default:
          break
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [queryClient])
}
