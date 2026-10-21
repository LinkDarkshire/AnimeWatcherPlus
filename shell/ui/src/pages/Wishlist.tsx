import { useEffect, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useAddToWishlist, useRemoveFromWishlist, useWishlist, useWishlistSearch } from "@/api/hooks"
import type { SharedPost } from "@/api/shell"
import type { WishlistCandidate, WishlistItem } from "@/api/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

const SEARCH_DEBOUNCE_MS = 300

export function Wishlist() {
  const t = useT()
  const location = useLocation()
  const navigate = useNavigate()
  // Text shared to the app from another one (Android share sheet).
  const shared = (location.state as { shared?: string } | null)?.shared
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

      {shared && (
        <SharedPostCard
          text={shared}
          adding={add.isPending}
          onAdd={(anidbId) => add.mutate(anidbId)}
          onDismiss={() => navigate(location.pathname, { replace: true, state: null })}
        />
      )}

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
                <CandidateRow
                  key={candidate.anidb_id}
                  candidate={candidate}
                  adding={add.isPending}
                  onAdd={() => add.mutate(candidate.anidb_id)}
                />
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

function CandidateRow({
  candidate,
  adding,
  onAdd,
}: {
  candidate: WishlistCandidate
  adding: boolean
  onAdd: () => void
}) {
  const t = useT()
  return (
    <div className="flex items-center justify-between gap-2 rounded border p-2 text-sm">
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
        <Button size="sm" className="shrink-0" disabled={adding} onClick={onAdd}>
          {t("wishlist.add")}
        </Button>
      )}
    </div>
  )
}

/** A post shared to the app: its text (fetched from X if it was a link) and
 * the anime titles the server recognized in it. */
function SharedPostCard({
  text,
  adding,
  onAdd,
  onDismiss,
}: {
  text: string
  adding: boolean
  onAdd: (anidbId: number) => void
  onDismiss: () => void
}) {
  const t = useT()
  const post = useQuery({
    queryKey: ["wishlist-shared", text],
    queryFn: () => api.post<SharedPost>("/api/v1/wishlist/shared", { text }),
  })

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium">{t("wishlist.sharedTitle")}</p>
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            {t("downloads.close")}
          </Button>
        </div>
        {post.isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}
        {post.isError && <p className="text-sm text-red-500">{post.error.message}</p>}
        {post.data && (
          <>
            {post.data.text && (
              <p className="line-clamp-4 text-xs whitespace-pre-line text-[hsl(var(--muted-foreground))]">
                {post.data.text}
              </p>
            )}
            {post.data.suggestions.length === 0 ? (
              <p className="text-sm">{t("wishlist.sharedNoMatch")}</p>
            ) : (
              <div className="space-y-1.5">
                {post.data.suggestions.map((candidate) => (
                  <CandidateRow
                    key={candidate.anidb_id}
                    candidate={candidate}
                    adding={adding}
                    onAdd={() => onAdd(candidate.anidb_id)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
