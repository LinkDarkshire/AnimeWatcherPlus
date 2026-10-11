import { useEffect } from "react"
import { Button } from "@/components/ui/button"
import { useT } from "@/i18n/I18nContext"
import { type ActionError, useErrorStore } from "@/lib/errorStore"

const AUTO_HIDE_MS = 10_000

/** Shows failed actions in the bottom right corner, with the reason the core
 * gave ("file is open in another program", ...). */
export function ErrorToasts() {
  const errors = useErrorStore((state) => state.errors)
  if (errors.length === 0) return null
  return (
    <div className="fixed right-4 bottom-4 z-50 flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
      {errors.map((error) => (
        <Toast key={error.id} error={error} />
      ))}
    </div>
  )
}

function Toast({ error }: { error: ActionError }) {
  const t = useT()
  const dismiss = useErrorStore((state) => state.dismiss)

  useEffect(() => {
    const timer = setTimeout(() => dismiss(error.id), AUTO_HIDE_MS)
    return () => clearTimeout(timer)
  }, [error.id, dismiss])

  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 shadow-lg dark:border-red-900 dark:bg-red-950 dark:text-red-200"
    >
      <div className="min-w-0 flex-1">
        <p className="font-medium">{t("errors.actionFailed")}</p>
        <p className="break-words">{error.message}</p>
      </div>
      <Button size="sm" variant="ghost" onClick={() => dismiss(error.id)}>
        ✕
      </Button>
    </div>
  )
}
