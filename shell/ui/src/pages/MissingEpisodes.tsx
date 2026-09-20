import { useState } from "react"
import { Link } from "react-router-dom"
import { useMissingEpisodesOverview } from "@/api/hooks"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useAssetUrl } from "@/lib/useAssetUrl"
import { useT } from "@/i18n/I18nContext"
import type { IncompleteAnime } from "@/api/types"

const PAGE_SIZE = 50

/** FA-12, global view: every series with at least one episode the provider
 * lists but that has no file on disk. */
export function MissingEpisodes() {
  const t = useT()
  const [page, setPage] = useState(1)
  const { data, isLoading, isError } = useMissingEpisodesOverview(page, PAGE_SIZE)

  const total = data?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">{t("missingEpisodes.title")}</h1>
        {data && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            {t("missingEpisodes.seriesCount", { count: total })}
          </span>
        )}
      </div>

      {isError && <p className="text-sm text-red-500">{t("library.loadError")}</p>}
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}
      {data?.items.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("missingEpisodes.empty")}</p>
      )}

      <div className="space-y-2">
        {data?.items.map((item) => <IncompleteRow key={item.anime_id} item={item} />)}
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            {t("common.previous")}
          </Button>
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            {t("common.pageOf", { page, pages: pageCount })}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={page >= pageCount}
            onClick={() => setPage(page + 1)}
          >
            {t("common.next")}
          </Button>
        </div>
      )}
    </div>
  )
}

function IncompleteRow({ item }: { item: IncompleteAnime }) {
  const t = useT()
  const posterUrl = useAssetUrl(item.poster_path)

  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-3">
        <div className="aspect-[2/3] w-12 shrink-0 overflow-hidden rounded bg-[hsl(var(--muted))]">
          {posterUrl && (
            <img src={posterUrl} alt="" className="h-full w-full object-cover" loading="lazy" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <Link to={`/animes/${item.anime_id}`} className="font-medium hover:underline">
            {item.title}
          </Link>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            {[item.year, item.media_type].filter(Boolean).join(" · ")}
          </p>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            {t("missingEpisodes.presentOfExpected", {
              present: item.present,
              expected: item.expected,
            })}
          </p>
        </div>
        <Badge variant="destructive">
          {t("animeCard.missingCount", { count: item.missing })}
        </Badge>
      </CardContent>
    </Card>
  )
}
