import { useQuery } from "@tanstack/react-query"
import { api, ApiError } from "@/api/client"
import { restartApp, shell, type Me, useShellConnection } from "@/api/shell"
import { Button } from "@/components/ui/button"
import { useT } from "@/i18n/I18nContext"

const RETRY_MS = 15_000

/** With the library on a server: says why nothing loads -- the server
 * can't be reached (left home without an internet address, server down) or
 * no longer accepts this device (revoked) -- instead of every page just
 * failing. */
export function ServerStatusBanner() {
  const t = useT()
  const { data: connection } = useShellConnection()
  const onServer = connection?.mode === "server" && !!connection.server
  const me = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => api.get<Me>("/api/v1/auth/me"),
    enabled: onServer,
    retry: false,
    refetchInterval: (query) => (query.state.status === "error" ? RETRY_MS : false),
  })

  if (!onServer || !me.isError) return null
  const revoked = me.error instanceof ApiError && (me.error.status === 401 || me.error.status === 403)

  const repair = async () => {
    if (!confirm(t("serverStatus.repairConfirm"))) return
    await shell.forget()
    if (connection?.platform === "mobile") window.location.reload()
    else await restartApp()
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-red-300 bg-red-50 px-4 py-2 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
      <span className="min-w-0 flex-1">
        {revoked
          ? t("serverStatus.revoked", { name: connection?.server?.name ?? "" })
          : t("serverStatus.unreachable", { message: me.error.message })}
      </span>
      {revoked && (
        <Button size="sm" variant="outline" onClick={repair}>
          {t("serverStatus.repair")}
        </Button>
      )}
    </div>
  )
}
