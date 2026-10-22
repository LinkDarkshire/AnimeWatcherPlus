import { useQuery } from "@tanstack/react-query"
import { api, ApiError, isTauri } from "./client"

// The app shell's commands for connecting to a server, QR codes and shared
// posts (shell/src-tauri/src/server.rs).

export type DataMode = "local" | "server"

export interface ServerConfig {
  name: string
  lan_url: string
  pairing_url: string
  internet_url: string | null
  device_id: number
  /** The server's own certificate, pinned when pairing. */
  tls_fingerprint: string | null
}

export interface ShellConnection {
  /** Phones have no library of their own: always a server. */
  platform: "desktop" | "mobile"
  port: number
  token: string
  /** The mode this run uses. */
  mode: DataMode
  /** The mode the next start uses (a switch needs a restart). */
  next_mode: DataMode
  server: ServerConfig | null
}

export interface ServerProbe {
  server_name: string
  version: string
  setup_required: boolean
  lan_url: string
  pairing_url: string
  tls_fingerprint: string
}

export interface PairStatus {
  status: "paired" | "pending" | "rejected"
  fingerprint: string | null
}

export interface PathMapping {
  source: string
  target: string
}

export interface ImportResult {
  tables: number
  rows: number
  plugins: number
  cache_files: number
  unmapped_folders: string[]
}

export interface PairingCode {
  code: string
  expires_in: number
}

export interface JoinRequest {
  id: string
  name: string
  fingerprint: string
}

export interface Device {
  id: number
  name: string
  fingerprint: string
  is_admin: boolean
  created_at: string
  last_seen_at: string | null
  revoked: boolean
}

export interface Me {
  mode: "desktop" | "server"
  server_name: string | null
  device_id: number | null
  device_name: string | null
  is_admin: boolean
}

/** A shell command; its errors become ApiErrors (status 0: no answer). */
async function command<T>(name: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core")
  try {
    return await invoke<T>(name, args)
  } catch (error) {
    if (error && typeof error === "object" && "message" in error) {
      const failure = error as { status?: number | null; message: string }
      throw new ApiError(failure.status ?? 0, failure.message)
    }
    throw new ApiError(0, String(error))
  }
}

export const shell = {
  available: isTauri,
  connection: () => command<ShellConnection>("get_connection_info"),
  probe: (address: string) => command<ServerProbe>("server_probe", { address }),
  pair: (args: {
    lanUrl: string
    pairingUrl: string
    serverName: string
    tlsFingerprint: string
    deviceName: string
    code: string
    setup: boolean
  }) => command<PairStatus>("server_pair", args),
  pairStatus: () => command<PairStatus>("server_pair_status"),
  setInternetUrl: (url: string | null) => command<void>("server_set_internet_url", { url }),
  switchMode: (mode: DataMode) => command<void>("switch_mode", { mode }),
  forget: () => command<void>("server_forget"),
  pushLibrary: (mappings: PathMapping[], force: boolean) =>
    command<ImportResult>("server_push_library", { mappings, force }),
  pullLibrary: (mappings: PathMapping[]) => command<void>("server_pull_library", { mappings }),
  pairingCall: <T>(method: "GET" | "POST", path: string, body?: unknown) =>
    command<T>("server_pairing_call", { method, path, body: body ?? null }),
  qrSvg: (text: string) => command<string>("qr_svg", { text }),
  takeSharedText: () => command<string | null>("take_shared_text"),
}

export interface SharedPost {
  text: string
  source_url: string | null
  suggestions: {
    anidb_id: number
    title: string
    matched_title: string
    score: number
    in_library: boolean
    on_wishlist: boolean
  }[]
}

/** Restarts the app; the shell stops its core first (see restart_app). */
export async function restartApp(): Promise<void> {
  const { invoke } = await import("@tauri-apps/api/core")
  await invoke("restart_app")
}

export function useShellConnection() {
  return useQuery({
    queryKey: ["shell-connection"],
    queryFn: shell.connection,
    enabled: shell.available(),
    staleTime: Infinity,
  })
}

/** Who this device is on the server (admin or not). */
export function useMe(enabled = true) {
  return useQuery({
    queryKey: ["auth-me"],
    queryFn: () => api.get<Me>("/api/v1/auth/me"),
    enabled,
  })
}

/** Folders can be shown in the file manager only in the desktop app with
 * its own data -- with a server they are on the server, not on this machine. */
export function useCanOpenFolders(): boolean {
  const { data: connection } = useShellConnection()
  return isTauri() && connection?.mode === "local"
}

export function useIsMobile(): boolean {
  return useShellConnection().data?.platform === "mobile"
}
