/** How this device reaches a server's folder: the server path prefix and
 * where it is here (a mounted path, \\server\share on Windows or an smb://
 * address). */
export interface FolderMapping {
  server: string
  local: string
}

function trimEnd(path: string): string {
  return path.replace(/[\\/]+$/, "")
}

/** `path` (as the server sees it) on this device, by the longest matching
 * mapping; null if none applies. Separators follow the local side. */
export function mapServerPath(path: string, mappings: FolderMapping[]): string | null {
  const sorted = [...mappings].sort((a, b) => trimEnd(b.server).length - trimEnd(a.server).length)
  for (const mapping of sorted) {
    const source = trimEnd(mapping.server)
    if (!source) continue
    if (path !== source && !path.startsWith(`${source}/`)) continue
    const rest = path.slice(source.length)
    const target = trimEnd(mapping.local)
    const windows = /^[a-zA-Z]:/.test(target) || target.startsWith("\\\\")
    return windows ? target + rest.replaceAll("/", "\\") : target + rest
  }
  return null
}
