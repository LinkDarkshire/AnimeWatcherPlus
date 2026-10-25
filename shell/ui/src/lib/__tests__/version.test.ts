import { describe, expect, it } from "vitest"
import { androidApkUrl, compareVersions } from "../version"

describe("compareVersions", () => {
  it("compares by number, not text", () => {
    expect(compareVersions("0.3.10", "0.3.9")).toBeGreaterThan(0)
    expect(compareVersions("0.4.0", "0.10.0")).toBeLessThan(0)
    expect(compareVersions("v1.0.0", "1.0")).toBe(0)
  })
})

describe("androidApkUrl", () => {
  it("points at the release asset", () => {
    expect(androidApkUrl("0.3.1")).toBe(
      "https://github.com/LinkDarkshire/AnimeWatcherPlus/releases/download/v0.3.1/AnimeWatcherPlus_0.3.1_android.apk",
    )
  })
})
