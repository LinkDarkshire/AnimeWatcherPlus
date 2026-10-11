import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useAnimesPage, useSettings, useTags } from "@/api/hooks"
import { AnimeCard } from "@/components/AnimeCard"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

const PAGE_SIZE_SETTING = "library_page_size"
const DEFAULT_PAGE_SIZE = 50
const PAGE_SIZES = [25, 50, 100]

/** Survives the unmount/remount that opening an anime and navigating back
 * causes. The page itself lives in the URL (?page=), so "back" restores it;
 * the text filters and the scroll offset within the page live here. Module
 * scope on purpose -- it has to outlive the component; plain view state,
 * reset on app reload. */
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

  const [searchParams, setSearchParams] = useSearchParams()
  const tag = searchParams.get("tag") ?? ""
  const page = Math.max(1, Number(searchParams.get("page")) || 1)
  const setPage = (next: number) => {
    viewState.scrollTop = 0
    const params = new URLSearchParams(searchParams)
    if (next > 1) params.set("page", String(next))
    else params.delete("page")
    setSearchParams(params)
    scrollRef.current?.scrollTo({ top: 0 })
  }
  // Any filter change reshuffles the list: back to page 1, top of the page.
  const resetToFirstPage = (update?: (params: URLSearchParams) => void) => {
    viewState.scrollTop = 0
    const params = new URLSearchParams(searchParams)
    params.delete("page")
    update?.(params)
    setSearchParams(params)
  }

  const [query, setQueryState] = useState(viewState.query)
  const [status, setStatusState] = useState(viewState.status)
  const [missingOnly, setMissingOnlyState] = useState(viewState.missingOnly)
  const setQuery = (value: string) => {
    viewState.query = value
    setQueryState(value)
    resetToFirstPage()
  }
  const setStatus = (value: string) => {
    viewState.status = value
    setStatusState(value)
    resetToFirstPage()
  }
  const setMissingOnly = (value: boolean) => {
    viewState.missingOnly = value
    setMissingOnlyState(value)
    resetToFirstPage()
  }
  const setTag = (value: string) =>
    resetToFirstPage((params) => (value ? params.set("tag", value) : params.delete("tag")))

  const { data: settings } = useSettings()
  const storedSize = settings?.values[PAGE_SIZE_SETTING]
  const pageSize = typeof storedSize === "number" && PAGE_SIZES.includes(storedSize) ? storedSize : DEFAULT_PAGE_SIZE

  const { data: tagsData } = useTags()
  const { data, isLoading, isError, isPlaceholderData } = useAnimesPage({
    query: query || undefined,
    status: status || undefined,
    tag: tag || undefined,
    missing: missingOnly || undefined,
    page,
    size: pageSize,
  })
  const total = data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / pageSize))

  // A smaller page size (or deleted anime) can leave the page number past the
  // end -- go to the last page that exists instead of showing an empty grid.
  useEffect(() => {
    if (data && !isPlaceholderData && page > pageCount) setPage(pageCount)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setPage is recreated every render
  }, [data, isPlaceholderData, page, pageCount])

  // Back from an anime: return to where the user was on this page. Once,
  // after the first real (non-placeholder) data has laid the grid out.
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const restoredRef = useRef(false)
  useLayoutEffect(() => {
    if (restoredRef.current || !data || isPlaceholderData) return
    restoredRef.current = true
    if (scrollRef.current && viewState.scrollTop > 0) scrollRef.current.scrollTop = viewState.scrollTop
  }, [data, isPlaceholderData])

  const pager = pageCount > 1 && (
    <div className="flex items-center justify-center gap-2 py-1">
      <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(1)}>
        «
      </Button>
      <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
        {t("common.previous")}
      </Button>
      <span className="text-sm text-[hsl(var(--muted-foreground))]">
        {t("common.pageOf", { page, pages: pageCount })}
      </span>
      <Button size="sm" variant="outline" disabled={page >= pageCount} onClick={() => setPage(page + 1)}>
        {t("common.next")}
      </Button>
      <Button size="sm" variant="outline" disabled={page >= pageCount} onClick={() => setPage(pageCount)}>
        »
      </Button>
    </div>
  )

  return (
    <div className="flex h-full flex-col gap-3 p-4">
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
          <input type="checkbox" checked={missingOnly} onChange={(e) => setMissingOnly(e.target.checked)} />
          {t("library.missingOnly")}
        </label>
        {data && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            {t("library.animeCount", { count: total })} · {t("library.pageSize", { count: pageSize })}
          </span>
        )}
      </div>

      {isError && <p className="text-sm text-red-500">{t("library.loadError")}</p>}
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}

      <div
        ref={scrollRef}
        onScroll={(e) => {
          if (restoredRef.current) viewState.scrollTop = e.currentTarget.scrollTop
        }}
        className="flex-1 space-y-3 overflow-auto"
      >
        {pager}
        <div
          className={`grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-4 transition-opacity ${
            isPlaceholderData ? "opacity-60" : ""
          }`}
        >
          {data?.items.map((anime) => (
            <AnimeCard key={anime.id} anime={anime} />
          ))}
        </div>
        {pager}
      </div>
    </div>
  )
}
