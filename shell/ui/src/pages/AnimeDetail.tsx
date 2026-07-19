import { Link, useNavigate, useParams } from "react-router-dom"
import { useState } from "react"
import { useAnime, useIdentifyAnime, useRefreshMetadata } from "@/api/hooks"
import { isTauri, openFolder } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { useAssetUrl } from "@/lib/useAssetUrl"
import { useT } from "@/i18n/I18nContext"

export function AnimeDetail() {
  const t = useT()
  const { id } = useParams()
  const animeId = id ? Number(id) : undefined
  const navigate = useNavigate()
  const { data: anime, isLoading } = useAnime(animeId)
  const refreshMetadata = useRefreshMetadata()
  const identify = useIdentifyAnime()
  const [manualId, setManualId] = useState("")
  const [changingId, setChangingId] = useState(false)
  const [newAnidbId, setNewAnidbId] = useState("")
  const posterUrl = useAssetUrl(anime?.poster_path)

  if (isLoading) return <p className="p-4 text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>
  if (!anime) return <p className="p-4 text-sm">{t("animeDetail.notFound")}</p>

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          {t("animeDetail.back")}
        </Button>
        {isTauri() && (
          <Button variant="outline" size="sm" onClick={() => openFolder(anime.directory_path)}>
            {t("animeDetail.openFolder")}
          </Button>
        )}
      </div>

      <div className="flex gap-4">
        <div className="aspect-[2/3] w-40 shrink-0 overflow-hidden rounded-md bg-[hsl(var(--muted))]">
          {posterUrl && (
            <img src={posterUrl} alt={anime.title} className="h-full w-full object-cover" />
          )}
        </div>
        <div className="space-y-2">
          <h1 className="text-xl font-semibold">{anime.title}</h1>
          {anime.original_title && (
            <p className="text-sm text-[hsl(var(--muted-foreground))]">{anime.original_title}</p>
          )}
          <div className="flex flex-wrap gap-2 text-sm text-[hsl(var(--muted-foreground))]">
            {anime.year && <span>{anime.year}</span>}
            {anime.media_type && <span>· {anime.media_type}</span>}
            {anime.anidb_id && <span>· AniDB #{anime.anidb_id}</span>}
          </div>
          {(anime.last_metadata_refresh || anime.last_episode_air_date) && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
              {anime.last_metadata_refresh && (
                <span>
                  {t("animeDetail.lastUpdate", {
                    date: new Date(anime.last_metadata_refresh).toLocaleDateString(),
                  })}
                </span>
              )}
              {anime.last_episode_air_date && (
                <span>
                  {t("animeDetail.lastEpisode", {
                    date: new Date(anime.last_episode_air_date).toLocaleDateString(),
                  })}
                </span>
              )}
              {anime.is_stale && <Badge variant="outline">{t("animeDetail.stale")}</Badge>}
            </div>
          )}
          {anime.is_duplicate && (
            <p className="text-sm text-amber-600 dark:text-amber-400">
              {t("animeDetail.duplicatePrefix")}{" "}
              {anime.duplicate_of_anime_id ? (
                <Link to={`/animes/${anime.duplicate_of_anime_id}`} className="underline">
                  {t("animeDetail.anotherFolder")}
                </Link>
              ) : (
                t("animeDetail.anotherFolder")
              )}
              .
            </p>
          )}
          <div className="flex flex-wrap gap-1.5">
            {anime.tags.map((tag) => (
              <Link key={tag.name} to={`/?tag=${encodeURIComponent(tag.name)}`}>
                <Badge className="cursor-pointer hover:opacity-80">{tag.name}</Badge>
              </Link>
            ))}
          </div>
          {anime.description && <p className="text-sm leading-relaxed">{anime.description}</p>}

          {anime.anidb_id && (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onClick={() => refreshMetadata.mutate(anime.id)}>
                {t("common.rescan")}
              </Button>
              {!changingId ? (
                <Button size="sm" variant="ghost" onClick={() => setChangingId(true)}>
                  {t("animeDetail.changeAnidbId")}
                </Button>
              ) : (
                <>
                  <Input
                    placeholder={t("animeDetail.newAnidbIdPlaceholder")}
                    value={newAnidbId}
                    onChange={(e) => setNewAnidbId(e.target.value)}
                    className="max-w-[160px]"
                  />
                  <Button
                    size="sm"
                    disabled={!newAnidbId || identify.isPending}
                    onClick={() => {
                      if (
                        confirm(
                          t("animeDetail.confirmChangeId", { from: anime.anidb_id ?? "", to: newAnidbId }),
                        )
                      ) {
                        identify.mutate({ animeId: anime.id, anidbId: Number(newAnidbId) })
                        setChangingId(false)
                        setNewAnidbId("")
                      }
                    }}
                  >
                    {t("animeDetail.change")}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setChangingId(false)}>
                    {t("common.cancel")}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {(anime.ident_status === "needs_manual_id" || anime.ident_status === "review") && (
        <Card>
          <CardContent className="space-y-3 p-4">
            <p className="text-sm font-medium">{t("animeDetail.manualIdentification")}</p>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">{anime.directory_path}</p>

            {anime.review_candidates && anime.review_candidates.length > 0 && (
              <div className="space-y-2">
                {anime.review_candidates.map((c) => (
                  <div key={c.aid} className="flex items-center justify-between rounded border p-2 text-sm">
                    <span>
                      {c.title}{" "}
                      <span className="text-[hsl(var(--muted-foreground))]">
                        {t("animeDetail.candidateInfo", { aid: c.aid, score: c.score.toFixed(0) })}
                      </span>
                    </span>
                    <Button size="sm" onClick={() => identify.mutate({ animeId: anime.id, anidbId: c.aid })}>
                      {t("common.apply")}
                    </Button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-center gap-2">
              <Input
                placeholder={t("animeDetail.enterAnidbId")}
                value={manualId}
                onChange={(e) => setManualId(e.target.value)}
                className="max-w-[180px]"
              />
              <Button
                size="sm"
                disabled={!manualId || identify.isPending}
                onClick={() => identify.mutate({ animeId: anime.id, anidbId: Number(manualId) })}
              >
                {t("common.assign")}
              </Button>
            </div>
            {identify.isError && (
              <p className="text-xs text-red-500">{t("animeDetail.identifyFailed")}</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
