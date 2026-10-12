import { Link } from "react-router-dom"
import { useRenameQueue, useResolveRename } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useT } from "@/i18n/I18nContext"

/** Anime whose directory name and/or matched episode filenames don't match
 * the canonical "{Title} - S01E{episode} - {episode title}" scheme --
 * unlike SortQueueSection, there's no target-folder choice here (renaming
 * always stays in the same parent directory), just a single confirmation
 * per entry. Shown alongside SortQueueSection/DuplicatesSection. */
export function RenameQueueSection() {
  const t = useT()
  const { data: items, isLoading } = useRenameQueue()
  const resolveRename = useResolveRename()

  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold">{t("renameQueue.title")}</h2>
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}
      {items?.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("renameQueue.empty")}</p>
      )}

      <div className="space-y-3">
        {items?.map((item) => (
          <Card key={item.anime_id}>
            <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <Link to={`/animes/${item.anime_id}`} className="font-medium hover:underline">
                  {item.title}
                </Link>
                <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">
                  {item.current_dir_name !== item.target_dir_name
                    ? `${item.current_dir_name} → ${item.target_dir_name}`
                    : item.current_dir_name}
                </p>
                {item.mismatched_file_count > 0 && (
                  <Badge variant="outline" className="mt-1">
                    {t("renameQueue.mismatchedFiles", { count: item.mismatched_file_count })}
                  </Badge>
                )}
              </div>
              <Button
                size="sm"
                disabled={resolveRename.isPending}
                onClick={() => resolveRename.mutate(item.anime_id)}
              >
                {t("renameQueue.rename")}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
