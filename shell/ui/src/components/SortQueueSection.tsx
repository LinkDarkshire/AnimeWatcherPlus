import { useState } from "react"
import { Link } from "react-router-dom"
import { useFolders, useResolveSort, useSortQueue } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useT } from "@/i18n/I18nContext"

/** Episodes identified in a download folder wait here for a manually-picked
 * target content folder (no rule engine -- see the sort_mode setting for the
 * "auto" alternative, which only ever acts when the target is unambiguous
 * and otherwise defers here too). Shown as its own section under the review
 * queue, mirroring DuplicatesSection. */
export function SortQueueSection() {
  const t = useT()
  const { data: items, isLoading } = useSortQueue()
  const { data: folders } = useFolders()
  const resolveSort = useResolveSort()
  const [selected, setSelected] = useState<Record<number, number | undefined>>({})

  const contentFolders = folders?.filter((f) => f.type === "content") ?? []

  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold">{t("sortQueue.title")}</h2>
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}
      {items?.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("sortQueue.empty")}</p>
      )}

      <div className="space-y-3">
        {items?.map((item) => {
          const targetFolderId = selected[item.anime_id] ?? item.suggested_target_folder_id ?? undefined
          return (
            <Card key={item.anime_id}>
              <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
                <div className="min-w-0">
                  <Link to={`/animes/${item.anime_id}`} className="font-medium hover:underline">
                    {item.title}
                  </Link>
                  <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">{item.directory_path}</p>
                  <Badge variant="outline" className="mt-1">
                    {t("sortQueue.matchedOf", { matched: item.matched_count, total: item.episode_count })}
                  </Badge>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <select
                    value={targetFolderId ?? ""}
                    onChange={(e) =>
                      setSelected((prev) => ({ ...prev, [item.anime_id]: Number(e.target.value) || undefined }))
                    }
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
                      resolveSort.mutate({ animeId: item.anime_id, targetFolderId })
                    }
                  >
                    {t("sortQueue.move")}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
