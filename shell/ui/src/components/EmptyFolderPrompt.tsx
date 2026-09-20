import { useDeleteEmptyDir, useDismissEmptyDir, usePendingEmptyDirs } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useT } from "@/i18n/I18nContext"

/** A newly-discovered directory with no video files never becomes an Anime
 * row (see scanner.py's has_video_files check) -- instead the backend
 * publishes "folder.empty_dir_found" over the WS event stream, which
 * useLiveEvents appends to the ["pending-empty-dirs"] query-cache-as-store.
 * This surfaces the oldest pending entry as an immediate confirmation
 * dialog, offering to delete the empty directory from disk. */
export function EmptyFolderPrompt() {
  const t = useT()
  const { data: pending } = usePendingEmptyDirs()
  const deleteEmptyDir = useDeleteEmptyDir()
  const dismiss = useDismissEmptyDir()

  const entry = pending?.[0]
  if (!entry) return null

  return (
    <Dialog open>
      <DialogContent onEscapeKeyDown={(e) => e.preventDefault()} onPointerDownOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>{t("emptyFolder.title")}</DialogTitle>
          <DialogDescription>{t("emptyFolder.description", { path: entry.path })}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={() => dismiss.mutate(entry)}>
            {t("emptyFolder.keep")}
          </Button>
          <Button variant="destructive" onClick={() => deleteEmptyDir.mutate(entry)}>
            {t("emptyFolder.delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
