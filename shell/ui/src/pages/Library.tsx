import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useVirtualizer } from "@tanstack/react-virtual"
import { useAnimesInfinite, useTags } from "@/api/hooks"
import { AnimeCard } from "@/components/AnimeCard"
import { Input } from "@/components/ui/input"
import { useContainerWidth } from "@/lib/useContainerWidth"
import { useT } from "@/i18n/I18nContext"

const CARD_MIN_WIDTH = 170
const GAP = 16
const ROW_HEIGHT = 330
const PAGE_SIZE = 100
/** Start loading the next page once the virtualizer renders within this many
 * rows of the end, so scrolling stays continuous instead of hitting a gap. */
const PREFETCH_ROW_MARGIN = 4

/** Survives the unmount/remount that opening an anime and navigating back
 * causes, so the user returns to the row they left from instead of the top of
 * the library. Module scope rather than component state on purpose -- the
 * whole point is that it outlives the component; it's plain view state, reset
 * on app reload. The filters travel with it because restoring a scroll offset
 * into a differently-filtered list would land somewhere arbitrary. */
const viewState = { scrollTop: 0, query: "", status: "", missingOnly: false }

export function Library() {
  const t = useT()
  const STATUS_OPTIONS = [
    { value: "", label: t("library.statusAll") },
    { value: "identified", label: t("library.statusIdentified") },
    { value: "pending", label: t("library.statusPending") },
    { value: "needs_manual_id", label: t("library.statusNeedsManualId") },
    { value: "review", label: t("library.statusReview") },
  ]
  const [query, setQueryState] = useState(viewState.query)
  const [status, setStatusState] = useState(viewState.status)
  // Changing a filter reshuffles the list, so the remembered offset is
  // meaningless from that point on -- drop it rather than restoring into an
  // unrelated row on the next return.
  const setQuery = (value: string) => {
    viewState.query = value
    viewState.scrollTop = 0
    setQueryState(value)
  }
  const setStatus = (value: string) => {
    viewState.status = value
    viewState.scrollTop = 0
    setStatusState(value)
  }
  const [missingOnly, setMissingOnlyState] = useState(viewState.missingOnly)
  const setMissingOnly = (value: boolean) => {
    viewState.missingOnly = value
    viewState.scrollTop = 0
    setMissingOnlyState(value)
  }
  const [searchParams, setSearchParams] = useSearchParams()
  const tag = searchParams.get("tag") ?? ""
  const setTag = (value: string) => {
    viewState.scrollTop = 0
    setSearchParams(value ? { tag: value } : {})
  }

  const { data: tagsData } = useTags()
  const { data, isLoading, isError, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useAnimesInfinite({
      query: query || undefined,
      status: status || undefined,
      tag: tag || undefined,
      missing: missingOnly || undefined,
      size: PAGE_SIZE,
    })

  const { ref: containerRef, width } = useContainerWidth<HTMLDivElement>()
  const columns = Math.max(1, Math.floor((width + GAP) / (CARD_MIN_WIDTH + GAP)))
  const items = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
  const total = data?.pages[0]?.total ?? 0
  const rowCount = Math.ceil(items.length / columns)

  const scrollParentRef = useMemo(() => ({ current: null as HTMLDivElement | null }), [])

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollParentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 3,
  })

  // Pull the next page in as the rendered window approaches the end of what's
  // loaded. Driven by the virtualizer's own output rather than a scroll
  // handler, so it stays correct regardless of row height or column count.
  const virtualRows = rowVirtualizer.getVirtualItems()
  const lastVisibleRow = virtualRows.length > 0 ? virtualRows[virtualRows.length - 1].index : 0
  useEffect(() => {
    if (!hasNextPage || isFetchingNextPage) return
    if (lastVisibleRow >= rowCount - PREFETCH_ROW_MARGIN) fetchNextPage()
  }, [lastVisibleRow, rowCount, hasNextPage, isFetchingNextPage, fetchNextPage])

  // Restore once, and only after both inputs to the layout are known: the
  // items (which give the spacer its height) and the measured width (which
  // decides the column count, and therefore how many rows that offset spans).
  // Restoring earlier would clamp against a too-short container or land on
  // the wrong row. useLayoutEffect keeps the jump from being painted.
  const restoredRef = useRef(false)
  useLayoutEffect(() => {
    if (restoredRef.current || width === 0 || rowCount === 0) return
    restoredRef.current = true
    const node = scrollParentRef.current
    if (node && viewState.scrollTop > 0) node.scrollTop = viewState.scrollTop
  }, [width, rowCount, scrollParentRef])

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
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={missingOnly}
            onChange={(e) => setMissingOnly(e.target.checked)}
          />
          {t("library.missingOnly")}
        </label>
        {data && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            {t("library.animeCount", { count: total })}
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
        onScroll={(e) => {
          // Ignore the browser's own reset-to-0 while the list is still
          // empty; otherwise remounting would overwrite the saved offset
          // before the restore above ever gets to use it.
          if (restoredRef.current) viewState.scrollTop = e.currentTarget.scrollTop
        }}
        className="flex-1 overflow-auto"
      >
        <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
          {virtualRows.map((virtualRow) => {
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
        {isFetchingNextPage && (
          <p className="py-2 text-center text-sm text-[hsl(var(--muted-foreground))]">
            {t("common.loading")}
          </p>
        )}
      </div>
    </div>
  )
}
