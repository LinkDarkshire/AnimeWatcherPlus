import { describe, expect, it } from "vitest"
import { mapServerPath } from "../folderMapping"

describe("mapServerPath", () => {
  const mappings = [
    { server: "/media", local: "smb://nas/media" },
    { server: "/media/Anime/", local: "\\\\nas\\anime" },
    { server: "/data", local: "/run/media/nas-data" },
  ]

  it("uses the longest matching prefix", () => {
    expect(mapServerPath("/media/Anime/Cowboy Bebop", mappings)).toBe("\\\\nas\\anime\\Cowboy Bebop")
    expect(mapServerPath("/media/Downloads", mappings)).toBe("smb://nas/media/Downloads")
    expect(mapServerPath("/data/plugins", mappings)).toBe("/run/media/nas-data/plugins")
  })

  it("matches whole path parts only", () => {
    expect(mapServerPath("/mediathek/x", mappings)).toBeNull()
    expect(mapServerPath("/media", mappings)).toBe("smb://nas/media")
  })

  it("returns null without a mapping", () => {
    expect(mapServerPath("/srv/other", mappings)).toBeNull()
    expect(mapServerPath("/media/x", [])).toBeNull()
  })
})
