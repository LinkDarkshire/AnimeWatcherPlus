interface ConnectionInfo {
  port: number
  token: string
}

interface Connection {
  baseUrl: string
  token: string
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window
}

/** Reveals a local directory in the OS file manager. Only works inside the
 * Tauri desktop shell -- there's no browser equivalent, so callers should
 * hide/disable the triggering UI when `isTauri()` is false. */
export async function openFolder(path: string): Promise<void> {
  const { invoke } = await import("@tauri-apps/api/core")
  await invoke("open_folder", { path })
}

let connectionPromise: Promise<Connection> | null = null

async function resolveConnection(): Promise<Connection> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core")
    const info = await invoke<ConnectionInfo>("get_connection_info")
    return { baseUrl: `http://127.0.0.1:${info.port}`, token: info.token }
  }
  return {
    baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000",
    token: import.meta.env.VITE_API_TOKEN ?? "",
  }
}

/** Resolves the Core's address once per session: via the Tauri sidecar
 * supervisor's `get_connection_info` command when running inside the desktop
 * shell, or from Vite env vars when running as a plain browser dev server.
 */
function getConnection(): Promise<Connection> {
  if (!connectionPromise) connectionPromise = resolveConnection()
  return connectionPromise
}

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { baseUrl, token } = await getConnection()
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // ignore body parse failure, fall back to statusText
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
}

/** Resolves a server-relative path (e.g. the `poster_path` returned by
 * /api/v1/animes) against the Core's actual base URL, for use in places that
 * can't go through `api.get()` -- e.g. an <img src> can't attach the
 * Authorization header, which is why the poster route doesn't require one.
 */
export async function resolveAssetUrl(path: string): Promise<string> {
  const { baseUrl } = await getConnection()
  return `${baseUrl}${path}`
}

export async function wsUrl(): Promise<string> {
  const { baseUrl, token } = await getConnection()
  const httpUrl = new URL(baseUrl)
  const proto = httpUrl.protocol === "https:" ? "wss:" : "ws:"
  const query = token ? `?token=${encodeURIComponent(token)}` : ""
  return `${proto}//${httpUrl.host}/ws${query}`
}
