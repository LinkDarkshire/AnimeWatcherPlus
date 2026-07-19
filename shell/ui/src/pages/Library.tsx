import { useMemo, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useVirtualizer } from "@tanstack/react-virtual"
import { useAnimes, useTags } from "@/api/hooks"
import { AnimeCard } from "@/components/AnimeCard"
import { Input } from "@/components/ui/input"
import { useContainerWidth } from "@/lib/useContainerWidth"
import { useT } from "@/i18n/I18nContext"

const CARD_MIN_WIDTH = 170
const GAP = 16
const ROW_HEIGHT = 330

export function Library() {
  const t = useT()
  const STATUS_OPTIONS = [
    { value: "", label: t("library.statusAll") },
    { value: "identified", label: t("library.statusIdentified") },
    { value: "pending", label: t("library.statusPending") },
    { value: "needs_manual_id", label: t("library.statusNeedsManualId") },
    { value: "review", label: t("library.statusReview") },
  ]
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("")
  const [searchParams, setSearchParams] = useSearchParams()
  const tag = searchParams.get("tag") ?? ""
  const setTag = (value: string) => setSearchParams(value ? { tag: value } : {})

  const { data: tagsData } = useTags()
  const { data, isLoading, isError } = useAnimes({
    query: query || undefined,
    status: status || undefined,
    tag: tag || undefined,
    size: 200,
  })

  const { ref: containerRef, width } = useContainerWidth<HTMLDivElement>()
  const columns = Math.max(1, Math.floor((width + GAP) / (CARD_MIN_WIDTH + GAP)))
  const items = data?.items ?? []
  const rowCount = Math.ceil(items.length / columns)

  const scrollParentRef = useMemo(() => ({ current: null as HTMLDivElement | null }), [])

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollParentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 3,
  })

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder={t("library.searchPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="max-w-xs"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
        >
          <option value="">{t("library.allTags")}</option>
          {tagsData?.map((tag) => (
            <option key={tag.id} value={tag.name}>
              {tag.name} ({tag.anime_count})
            </option>
          ))}
        </select>
        {data && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            {t("library.animeCount", { count: data.total })}
          </span>
        )}
      </div>

      {isError && <p className="text-sm text-red-500">{t("library.loadError")}</p>}
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}

      <div
        ref={(node) => {
          containerRef.current = node
          scrollParentRef.current = node
        }}
        className="flex-1 overflow-auto"
      >
        <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const startIndex = virtualRow.index * columns
            const rowItems = items.slice(startIndex, startIndex + columns)
            return (
              <div
                key={virtualRow.key}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: virtualRow.size,
                  transform: `translateY(${virtualRow.start}px)`,
                  display: "grid",
                  gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                  gap: GAP,
                  paddingBottom: GAP,
                }}
              >
                {rowItems.map((anime) => (
                  <AnimeCard key={anime.id} anime={anime} />
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
