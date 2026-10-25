import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import { useMe, useShellConnection } from "@/api/shell"
import { useT } from "@/i18n/I18nContext"
import { compareVersions } from "@/lib/version"

interface ServerRelease {
  current: string
  latest: string | null
  update_available: boolean
  url: string | null
}

const UPDATE_COMMAND = "docker compose pull && docker compose up -d"

/** With a server: says when the server is the one behind -- this app is
 * newer than the server, or (for admins) a newer server release is out.
 * The apps follow the server's version on their own (UpdateGate); the
 * server is updated with docker. */
export function VersionNotice() {
  const t = useT()
  const { data: connection } = useShellConnection()
  const onServer = connection?.mode === "server" && !!connection.server
  const me = useMe(onServer)
  const appVersion = useQuery({
    queryKey: ["app-version"],
    queryFn: async () => (await import("@tauri-apps/api/app")).getVersion(),
    enabled: onServer,
    staleTime: Infinity,
  })
  const release = useQuery({
    queryKey: ["server-release"],
    queryFn: () => api.get<ServerRelease>("/api/v1/updates/server"),
    enabled: onServer && !!me.data?.is_admin,
    staleTime: 6 * 3600_000,
  })

  if (!onServer || !me.data) return null
  const serverBehindApp = appVersion.data && compareVersions(appVersion.data, me.data.server_version) > 0
  const newerRelease = release.data?.update_available ? release.data.latest : null
  if (!serverBehindApp && !newerRelease) return null

  return (
    <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
      {serverBehindApp
        ? t("versionNotice.serverBehind", { server: me.data.server_version, app: appVersion.data ?? "" })
        : t("versionNotice.serverUpdate", { version: newerRelease ?? "" })}{" "}
      <code className="rounded bg-black/10 px-1 text-xs dark:bg-white/10">{UPDATE_COMMAND}</code>
    </div>
  )
}
