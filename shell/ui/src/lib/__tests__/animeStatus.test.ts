import { describe, expect, it } from "vitest"
import { getStatusLabelKey, getStatusVariant } from "@/lib/animeStatus"

describe("getStatusVariant", () => {
  it("maps identified to the default (positive) badge variant", () => {
    expect(getStatusVariant("identified")).toBe("default")
  })

  it("maps needs_manual_id and review to the destructive variant", () => {
    expect(getStatusVariant("needs_manual_id")).toBe("destructive")
    expect(getStatusVariant("review")).toBe("destructive")
  })

  it("maps pending to the outline variant", () => {
    expect(getStatusVariant("pending")).toBe("outline")
  })
})

describe("getStatusLabelKey", () => {
  it("maps every status to a distinct translation key", () => {
    const keys = (["identified", "pending", "needs_manual_id", "review"] as const).map(
      getStatusLabelKey,
    )
    expect(new Set(keys).size).toBe(4)
  })
})
