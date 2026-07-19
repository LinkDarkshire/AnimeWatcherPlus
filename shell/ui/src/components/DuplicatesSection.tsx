import { useState } from "react"
import { Link } from "react-router-dom"
import { useDeleteAnime, useDuplicates, useIdentifyAnime } from "@/api/hooks"
import { isTauri, openFolder } from "@/api/client"
import { useAssetUrl } from "@/lib/useAssetUrl"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { useT } from "@/i18n/I18nContext"

function GroupPoster({ posterPath, title }: { posterPath: string | null; title: string }) {
  const posterUrl = useAssetUrl(posterPath ?? undefined)
  if (!posterUrl) return null
  return <img src={posterUrl} alt={title} className="h-16 w-11 shrink-0 rounded object-cover" />
}

/** Kap. FA-29 follow-up: two catalog entries sharing the same AniDB ID need
 * a human decision -- either one was misidentified (change its ID) or it's
 * a genuine duplicate copy (delete one entry). Shown as its own section
 * under the review queue, per user request. */
export function DuplicatesSection() {
  const t = useT()
  const { data: groups, isLoading } = useDuplicates()
  const identify = useIdentifyAnime()
  const deleteAnime = useDeleteAnime()
  const [editingAnimeId, setEditingAnimeId] = useState<number | null>(null)
  const [newIdValue, setNewIdValue] = useState("")

  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold">{t("duplicates.title")}</h2>
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}
      {groups?.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("duplicates.empty")}</p>
      )}

      <div className="space-y-4">
        {groups?.map((group) => (
          <Card key={group.anidb_id}>
            <CardContent className="space-y-3 p-4">
              <div className="flex items-center gap-3">
                <GroupPoster posterPath={group.entries[0]?.poster_path ?? null} title={group.title} />
                <div className="min-w-0">
                  <p className="truncate font-medium">{group.title}</p>
                  <p className="text-xs text-[hsl(var(--muted-foreground))]">AniDB #{group.anidb_id}</p>
                </div>
              </div>

              <div className="space-y-2 rounded-md border p-2">
                {group.entries.map((entry) => (
                  <div
                    key={entry.anime_id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm"
                  >
                    <Link to={`/animes/${entry.anime_id}`} className="min-w-0 truncate hover:underline">
                      {entry.directory_path}
                    </Link>
                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                      {editingAnimeId === entry.anime_id ? (
                        <>
                          <Input
                            placeholder={t("animeDetail.newAnidbIdPlaceholder")}
                            value={newIdValue}
                            onChange={(e) => setNewIdValue(e.target.value)}
                            className="max-w-[140px]"
                          />
                          <Button
                            size="sm"
                            disabled={!newIdValue || identify.isPending}
                            onClick={() => {
                              identify.mutate({ animeId: entry.anime_id, anidbId: Number(newIdValue) })
                              setEditingAnimeId(null)
                              setNewIdValue("")
                            }}
                          >
                            {t("animeDetail.change")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditingAnimeId(null)}>
                            {t("common.cancel")}
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setEditingAnimeId(entry.anime_id)
                            setNewIdValue("")
                          }}
                        >
                          {t("duplicates.changeId")}
                        </Button>
                      )}
                      {isTauri() && (
                        <Button size="sm" variant="outline" onClick={() => openFolder(entry.directory_path)}>
                          {t("animeDetail.openFolder")}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => {
                          if (confirm(t("duplicates.confirmDelete", { path: entry.directory_path }))) {
                            deleteAnime.mutate(entry.anime_id)
                          }
                        }}
                      >
                        {t("duplicates.delete")}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
