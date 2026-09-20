import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAnimePendingActions, useFolders, useResolveRename, useResolveSort } from "@/api/hooks"
import { ApiError } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useT } from "@/i18n/I18nContext"
import type { RenameProposal, SortProposal } from "@/api/types"

/** How many file renames to list before collapsing the rest -- a long series
 * can have dozens, and the card shouldn't push everything else off-screen. */
const COLLAPSED_FILE_COUNT = 5

/** The rename/sort requests from the Abfragen page that concern this one
 * series, resolvable right here. Identification and duplicates already have
 * their own place on the series page. */
export function AnimePendingActionsSection({ animeId }: { animeId: number }) {
  const t = useT()
  const { data } = useAnimePendingActions(animeId)

  if (!data || (!data.rename && !data.sort)) return null

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <p className="text-sm font-medium">{t("animePending.title")}</p>
        {data.sort && <SortRequest animeId={animeId} proposal={data.sort} />}
        {data.rename && <RenameRequest animeId={animeId} proposal={data.rename} />}
      </CardContent>
    </Card>
  )
}

function errorDetail(error: unknown): string {
  return error instanceof ApiError ? error.detail : String(error)
}

function RenameRequest({ animeId, proposal }: { animeId: number; proposal: RenameProposal }) {
  const t = useT()
  const resolveRename = useResolveRename()
  const [expanded, setExpanded] = useState(false)

  const files = proposal.file_renames
  const shownFiles = expanded ? files : files.slice(0, COLLAPSED_FILE_COUNT)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm">{t("animePending.renameTitle")}</p>
        {files.length > 0 && (
          <Badge variant="outline">{t("animePending.fileCount", { count: files.length })}</Badge>
        )}
      </div>

      {proposal.dir_needs_rename && (
        <p className="break-all text-xs">
          <span className="text-[hsl(var(--muted-foreground))]">{t("animePending.folder")}: </span>
          {proposal.current_dir_name} → <strong>{proposal.target_dir_name}</strong>
        </p>
      )}

      {files.length > 0 && (
        <ul className="space-y-1">
          {shownFiles.map((file) => (
            <li
              key={file.current}
              className="rounded border border-[hsl(var(--border))] px-2 py-1 font-mono text-xs break-all"
            >
              <span className="text-[hsl(var(--muted-foreground))]">{file.current}</span>
              <br />→ {file.target}
            </li>
          ))}
        </ul>
      )}
      {files.length > COLLAPSED_FILE_COUNT && (
        <Button size="sm" variant="ghost" onClick={() => setExpanded(!expanded)}>
          {expanded
            ? t("animePending.showLess")
            : t("animePending.showAll", { count: files.length })}
        </Button>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={resolveRename.isPending}
          onClick={() => resolveRename.mutate(animeId)}
        >
          {t("animePending.renameNow")}
        </Button>
        {resolveRename.isError && (
          <span className="text-xs text-red-500">
            {t("animePending.failed", { detail: errorDetail(resolveRename.error) })}
          </span>
        )}
      </div>
    </div>
  )
}

function SortRequest({ animeId, proposal }: { animeId: number; proposal: SortProposal }) {
  const t = useT()
  const navigate = useNavigate()
  const { data: folders } = useFolders()
  const resolveSort = useResolveSort()
  const [selected, setSelected] = useState<number | undefined>()

  const contentFolders = folders?.filter((f) => f.type === "content") ?? []
  const targetFolderId = selected ?? proposal.suggested_target_folder_id ?? undefined

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm">{t("animePending.sortTitle")}</p>
        <Badge variant="outline">
          {t("sortQueue.matchedOf", { matched: proposal.matched_count, total: proposal.episode_count })}
        </Badge>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={targetFolderId ?? ""}
          onChange={(e) => setSelected(Number(e.target.value) || undefined)}
          className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
        >
          <option value="" disabled>
            {t("sortQueue.selectFolder")}
          </option>
          {contentFolders.map((folder) => (
            <option key={folder.id} value={folder.id}>
              {folder.name}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          disabled={!targetFolderId || resolveSort.isPending}
          onClick={() =>
            targetFolderId &&
            resolveSort.mutate(
              { animeId, targetFolderId },
              {
                // Merging into an existing copy of the series deletes this
                // entry; follow the episodes to where they went instead of
                // leaving the user on a page that no longer exists.
                onSuccess: (result) => {
                  if (result.target_anime_id !== animeId) {
                    navigate(`/animes/${result.target_anime_id}`, { replace: true })
                  }
                },
              },
            )
          }
        >
          {t("sortQueue.move")}
        </Button>
        {resolveSort.isError && (
          <span className="text-xs text-red-500">
            {t("animePending.failed", { detail: errorDetail(resolveSort.error) })}
          </span>
        )}
      </div>
    </div>
  )
}
