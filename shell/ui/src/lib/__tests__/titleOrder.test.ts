import { describe, expect, it } from "vitest"
import { DEFAULT_TITLE_ORDER, moveTitleVariant, normalizeTitleOrder } from "../titleOrder"

describe("normalizeTitleOrder", () => {
  it("keeps a complete order as-is", () => {
    expect(normalizeTitleOrder(["main", "ja", "en"])).toEqual(["main", "ja", "en"])
  })

  it("completes a partial order with the remaining variants", () => {
    expect(normalizeTitleOrder(["ja"])).toEqual(["ja", "en", "main"])
  })

  it("drops unknown and duplicate entries", () => {
    expect(normalizeTitleOrder(["en", "en", "klingon", "ja"])).toEqual(["en", "ja", "main"])
  })

  it("falls back to the default for anything that isn't a list", () => {
    for (const value of [undefined, null, "en", 42, { en: 1 }]) {
      expect(normalizeTitleOrder(value)).toEqual(DEFAULT_TITLE_ORDER)
    }
  })
})

describe("moveTitleVariant", () => {
  it("swaps two neighbours", () => {
    expect(moveTitleVariant(["en", "main", "ja"], 1, 0)).toEqual(["main", "en", "ja"])
    expect(moveTitleVariant(["en", "main", "ja"], 1, 2)).toEqual(["en", "ja", "main"])
  })

  it("returns the order unchanged when the target index is out of bounds", () => {
    const order = DEFAULT_TITLE_ORDER
    expect(moveTitleVariant(order, 0, -1)).toBe(order)
    expect(moveTitleVariant(order, 2, 3)).toBe(order)
  })
})
