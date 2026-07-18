import { describe, expect, it } from "vitest"
import { getStatusPresentation } from "@/lib/animeStatus"

describe("getStatusPresentation", () => {
  it("maps identified to the default (positive) badge variant", () => {
    expect(getStatusPresentation("identified")).toEqual({
      label: "Identifiziert",
      variant: "default",
    })
  })

  it("maps needs_manual_id and review to the destructive variant", () => {
    expect(getStatusPresentation("needs_manual_id").variant).toBe("destructive")
    expect(getStatusPresentation("review").variant).toBe("destructive")
  })

  it("maps pending to the outline variant", () => {
    expect(getStatusPresentation("pending").variant).toBe("outline")
  })
})
