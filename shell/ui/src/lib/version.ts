/** Release versions ("0.3.10", "v1.0.0") compared by their numbers: <0, 0, >0. */
export function compareVersions(a: string, b: string): number {
  const parse = (v: string) =>
    v
      .trim()
      .replace(/^v/i, "")
      .split(".")
      .map((part) => Number.parseInt(part, 10))
      .map((n) => (Number.isNaN(n) ? 0 : n))
  const left = parse(a)
  const right = parse(b)
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

const RELEASES = "https://github.com/LinkDarkshire/AnimeWatcherPlus/releases"

/** The Android app of one release (installed over the old one). */
export function androidApkUrl(version: string): string {
  return `${RELEASES}/download/v${version}/AnimeWatcherPlus_${version}_android.apk`
}
