import { useState } from "react"
import { useLocalEpisodes, useMissingEpisodes, useUpdateEpisodeNumber } from "@/api/hooks"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"
import type { LocalEpisodeItem } from "@/api/types"

/** FA-12 per series: the soll/ist comparison plus the manual episode-number
 * correction the concept calls for, since filename parsing can't cover every
 * release naming scheme. */
export function EpisodeSection({ animeId }: { animeId: number }) {
  const t = useT()
  const { data: missing } = useMissingEpisodes(animeId)
  const { data: episodes } = useLocalEpisodes(animeId)
  const [editing, setEditing] = useState(false)

  if (!missing || missing.expected === 0) return null

  const complete = missing.missing.length === 0

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-medium">{t("missingEpisodes.sectionTitle")}</p>
          <Badge variant={complete ? "outline" : "destructive"}>
            {t("missingEpisodes.presentOfExpected", {
              present: missing.present,
              expected: missing.expected,
            })}
          </Badge>
        </div>

        {complete ? (
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            {t("missingEpisodes.allPresent")}
          </p>
        ) : (
          <ul className="space-y-1">
            {missing.missing.map((episode) => (
              <li
                key={episode.ep_number}
                className="flex items-baseline gap-2 rounded border border-[hsl(var(--border))] px-2 py-1.5 text-sm"
              >
                <span className="font-mono text-xs text-[hsl(var(--muted-foreground))]">
                  {t("missingEpisodes.episodeShort", { number: episode.ep_number })}
                </span>
                <span className="min-w-0 flex-1 truncate">{episode.title ?? "—"}</span>
                {episode.air_date && (
                  <span className="shrink-0 text-xs text-[hsl(var(--muted-foreground))]">
                    {new Date(episode.air_date).toLocaleDateString()}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}

        <Button size="sm" variant="ghost" onClick={() => setEditing(!editing)}>
          {editing ? t("missingEpisodes.hideFiles") : t("missingEpisodes.showFiles")}
        </Button>

        {editing && (
          <div className="space-y-1">
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              {t("missingEpisodes.correctionHint")}
            </p>
            {episodes?.map((episode) => (
              <EpisodeRow key={episode.id} animeId={animeId} episode={episode} />
            ))}
            {episodes?.length === 0 && (
              <p className="text-xs text-[hsl(var(--muted-foreground))]">
                {t("missingEpisodes.noFiles")}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function EpisodeRow({ animeId, episode }: { animeId: number; episode: LocalEpisodeItem }) {
  const t = useT()
  const update = useUpdateEpisodeNumber()
  const [value, setValue] = useState(episode.ep_number ?? "")

  const dirty = (episode.ep_number ?? "") !== value.trim()

  return (
    <div className="flex items-center gap-2 rounded border border-[hsl(var(--border))] px-2 py-1.5 text-sm">
      <span className="min-w-0 flex-1 truncate" title={episode.file_name}>
        {episode.file_name}
      </span>
      {episode.manual_override && (
        <Badge variant="outline">{t("missingEpisodes.manual")}</Badge>
      )}
      <Input
        value={value}
        inputMode="numeric"
        placeholder={t("missingEpisodes.numberPlaceholder")}
        onChange={(e) => setValue(e.target.value)}
        className="h-8 w-20"
      />
      <Button
        size="sm"
        disabled={!dirty || update.isPending}
        onClick={() =>
          update.mutate({
            animeId,
            episodeId: episode.id,
            epNumber: value.trim() === "" ? null : value.trim(),
          })
        }
      >
        {t("common.save")}
      </Button>
    </div>
  )
}
