import { describe, expect, it } from "vitest"
import { toQueryString } from "@/lib/animeFilters"

describe("toQueryString", () => {
  it("defaults to page 1 and size 60 with no filters", () => {
    expect(toQueryString({})).toBe("page=1&size=60")
  })

  it("includes only set filters", () => {
    const qs = toQueryString({ query: "Mushoku", tag: "isekai" })
    const params = new URLSearchParams(qs)
    expect(params.get("query")).toBe("Mushoku")
    expect(params.get("tag")).toBe("isekai")
    expect(params.get("year")).toBeNull()
    expect(params.get("page")).toBe("1")
  })

  it("respects explicit page and size", () => {
    const qs = toQueryString({ page: 3, size: 25 })
    const params = new URLSearchParams(qs)
    expect(params.get("page")).toBe("3")
    expect(params.get("size")).toBe("25")
  })

  it("omits falsy year/type/status", () => {
    const qs = toQueryString({ year: 0, type: "", status: undefined })
    const params = new URLSearchParams(qs)
    expect(params.get("year")).toBeNull()
    expect(params.get("type")).toBeNull()
    expect(params.get("status")).toBeNull()
  })
})
