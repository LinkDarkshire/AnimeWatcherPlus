/** "1.5 GB" from a byte count; null for nothing/zero. */
export function formatSize(bytes: number | null): string | null {
  if (!bytes) return null
  const units = ["B", "KB", "MB", "GB", "TB"]
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}
