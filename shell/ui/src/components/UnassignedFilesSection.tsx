import { useState } from "react"
import { Link } from "react-router-dom"
import { useMediaScan, useUnassignedFiles, useUpdateEpisodeNumber } from "@/api/hooks"
import type { UnassignedGroup } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useT } from "@/i18n/I18nContext"

/** Video files the app couldn't match to an episode (no number in the file
 * name, or one AniDB doesn't list). The user picks the right episode; that
 * choice is stored as a manual number, so later scans keep it. */
export function UnassignedFilesSection() {
  const t = useT()
  const { data: groups, isLoading } = useUnassignedFiles()
  const mediaScan = useMediaScan()

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{t("unassigned.title")}</h2>
        <Button size="sm" variant="outline" disabled={mediaScan.isPending} onClick={() => mediaScan.mutate()}>
          {mediaScan.isPending ? t("unassigned.mediaScanRunning") : t("unassigned.mediaScan")}
        </Button>
      </div>
      <p className="text-xs text-[hsl(var(--muted-foreground))]">{t("unassigned.description")}</p>
      {mediaScan.isSuccess && (
        <p className="text-xs text-emerald-600">
          {t("unassigned.mediaScanQueued", { count: mediaScan.data.folders })}
        </p>
      )}
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}
      {groups?.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("unassigned.empty")}</p>
      )}
      {groups?.map((group) => (
        <UnassignedGroupCard key={group.anime_id} group={group} />
      ))}
    </div>
  )
}

function UnassignedGroupCard({ group }: { group: UnassignedGroup }) {
  const t = useT()
  const update = useUpdateEpisodeNumber()
  const [choices, setChoices] = useState<Record<number, string>>({})

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <Link to={`/animes/${group.anime_id}`} className="font-medium hover:underline">
          {group.title}
        </Link>
        {group.files.map((file) => {
          const choice = choices[file.episode_id] ?? ""
          return (
            <div
              key={file.episode_id}
              className="space-y-2 rounded border border-[hsl(var(--border))] p-2 text-sm"
            >
              {/* The full name, wrapped -- it's what the user decides by. */}
              <div>
                <p className="break-all">{file.file_name}</p>
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  {file.ep_number === null
                    ? t("unassigned.noNumber")
                    : t("unassigned.unknownNumber", { number: file.ep_number })}
                </p>
              </div>
              <div className="flex gap-2">
                <select
                  value={choice}
                  onChange={(e) => setChoices((prev) => ({ ...prev, [file.episode_id]: e.target.value }))}
                  // Explicit colors: the native dropdown list otherwise ends
                  // up unreadable in the dark theme on some systems.
                  className="h-9 min-w-0 flex-1 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 text-sm text-[hsl(var(--foreground))]"
                >
                  {/* A normal option, not a disabled one: some webviews show
                      a disabled placeholder as an empty box. */}
                  <option value="">{t("unassigned.pick")}</option>
                  <option value="extra">{t("unassigned.extra")}</option>
                {group.episodes.map((episode) => (
                  <option key={episode.ep_number} value={episode.ep_number}>
                    {`${t(/^\d+$/.test(episode.ep_number) ? "unassigned.episodeOption" : "unassigned.specialOption", {
                      number: episode.ep_number,
                    })}${episode.title ? ` – ${episode.title}` : ""}`}
                  </option>
                ))}
                </select>
                <Button
                  disabled={!choice || update.isPending}
                  onClick={() =>
                    update.mutate({ animeId: group.anime_id, episodeId: file.episode_id, epNumber: choice })
                  }
                >
                  {t("common.save")}
                </Button>
              </div>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
