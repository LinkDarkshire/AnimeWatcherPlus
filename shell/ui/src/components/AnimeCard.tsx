import { Link } from "react-router-dom"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { getStatusLabelKey, getStatusVariant } from "@/lib/animeStatus"
import { useAssetUrl } from "@/lib/useAssetUrl"
import { useT } from "@/i18n/I18nContext"
import type { AnimeListItem } from "@/api/types"

export function AnimeCard({ anime }: { anime: AnimeListItem }) {
  const t = useT()
  const variant = getStatusVariant(anime.ident_status)
  const posterUrl = useAssetUrl(anime.poster_path)
  return (
    <Link to={`/animes/${anime.id}`}>
      <Card className="h-full overflow-hidden transition-shadow hover:shadow-md">
        <div className="aspect-[2/3] w-full bg-[hsl(var(--muted))]">
          {posterUrl ? (
            <img
              src={posterUrl}
              alt={anime.title}
              className="h-full w-full object-cover"
              loading="lazy"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">
              {t("animeCard.noArtwork")}
            </div>
          )}
        </div>
        <CardContent className="space-y-1.5 p-3">
          <p className="line-clamp-2 text-sm font-medium leading-tight">{anime.title}</p>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
            {anime.year && <span>{anime.year}</span>}
            {anime.media_type && <span>· {anime.media_type}</span>}
          </div>
          <div className="flex flex-wrap gap-1.5 pt-1">
            <Badge variant={variant}>{t(getStatusLabelKey(anime.ident_status))}</Badge>
            {anime.missing_on_disk && <Badge variant="destructive">{t("animeCard.missing")}</Badge>}
            {anime.is_duplicate && <Badge variant="outline">{t("animeCard.duplicate")}</Badge>}
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
