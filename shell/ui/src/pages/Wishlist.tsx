import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useAddToWishlist, useRemoveFromWishlist, useWishlist, useWishlistSearch } from "@/api/hooks"
import type { WishlistItem } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

const SEARCH_DEBOUNCE_MS = 300

export function Wishlist() {
  const t = useT()
  const [input, setInput] = useState("")
  const [query, setQuery] = useState("")

  useEffect(() => {
    const timer = setTimeout(() => setQuery(input), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [input])

  const { data: entries, isLoading } = useWishlist()
  const search = useWishlistSearch(query)
  const add = useAddToWishlist()
  const remove = useRemoveFromWishlist()
  const searching = query.trim().length >= 2

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <div className="space-y-1">
        <h1 className="text-lg font-semibold">{t("wishlist.title")}</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("wishlist.description")}</p>
      </div>

      <Card>
        <CardContent className="space-y-3 p-4">
          <Input
            placeholder={t("wishlist.searchPlaceholder")}
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          {!searching && (
            <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("wishlist.searchHint")}</p>
          )}
          {searching && search.isLoading && (
            <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>
          )}
          {searching && search.data?.length === 0 && (
            <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("wishlist.noResults")}</p>
          )}
          {add.isError && (
            <p className="text-sm text-red-500">
              {t("wishlist.addFailed", { message: add.error.message })}
            </p>
          )}
          {searching && (
            <div className="space-y-1.5">
              {search.data?.map((candidate) => (
                <div
                  key={candidate.anidb_id}
                  className="flex items-center justify-between gap-2 rounded border p-2 text-sm"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{candidate.title}</p>
                    <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">
                      AniDB #{candidate.anidb_id}
                      {candidate.matched_title !== candidate.title &&
                        ` · ${t("wishlist.matchedVia", { title: candidate.matched_title })}`}
                    </p>
                  </div>
                  {candidate.in_library ? (
                    <Badge variant="outline">{t("wishlist.inLibrary")}</Badge>
                  ) : candidate.on_wishlist ? (
                    <Badge variant="outline">{t("wishlist.onWishlist")}</Badge>
                  ) : (
                    <Button
                      size="sm"
                      disabled={add.isPending}
                      onClick={() => add.mutate(candidate.anidb_id)}
                    >
                      {t("wishlist.add")}
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}
      {entries?.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("wishlist.empty")}</p>
      )}

      <div className="space-y-2">
        {entries?.map((entry) => (
          <WishlistRow
            key={entry.id}
            entry={entry}
            removing={remove.isPending && remove.variables === entry.id}
            onRemove={() => remove.mutate(entry.id)}
          />
        ))}
      </div>
    </div>
  )
}

function WishlistRow({
  entry,
  removing,
  onRemove,
}: {
  entry: WishlistItem
  removing: boolean
  onRemove: () => void
}) {
  const t = useT()
  const details = [
    entry.year,
    entry.media_type,
    entry.episode_count ? t("wishlist.episodes", { count: entry.episode_count }) : null,
  ].filter(Boolean)

  return (
    <Card>
      <CardContent className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <div className="min-w-0 space-y-0.5">
          {entry.library_anime_id ? (
            <Link to={`/animes/${entry.library_anime_id}`} className="block font-medium hover:underline sm:truncate">
              {entry.title}
            </Link>
          ) : (
            <p className="font-medium sm:truncate">{entry.title}</p>
          )}
          <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">
            AniDB #{entry.anidb_id}
            {details.length > 0 && ` · ${details.join(" · ")}`}
            {details.length === 0 && entry.details_pending && ` · ${t("wishlist.detailsPending")}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center justify-between gap-2">
          {entry.library_anime_id ? (
            <Badge variant="default">{t("wishlist.inLibrary")}</Badge>
          ) : (
            <Badge variant="outline" className="border-amber-400 text-amber-600 dark:text-amber-400">
              {t("wishlist.notAvailable")}
            </Badge>
          )}
          <Button size="sm" variant="ghost" disabled={removing} onClick={onRemove}>
            {t("wishlist.remove")}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
