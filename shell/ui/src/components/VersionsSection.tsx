import { useQuery } from "@tanstack/react-query"
import { isTauri } from "@/api/client"
import { useMe, useShellConnection } from "@/api/shell"
import { Card, CardContent } from "@/components/ui/card"
import { useT } from "@/i18n/I18nContext"

/** Which version this app is and which the server (or the app's own core)
 * runs -- with a server, the apps follow its version on their own. */
export function VersionsSection() {
  const t = useT()
  const { data: connection } = useShellConnection()
  const me = useMe()
  const appVersion = useQuery({
    queryKey: ["app-version"],
    queryFn: async () => (await import("@tauri-apps/api/app")).getVersion(),
    enabled: isTauri(),
    staleTime: Infinity,
  })
  const onServer = connection?.mode === "server"

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <p className="text-sm font-medium">{t("versions.title")}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {isTauri() && (
            <>
              <dt className="text-[hsl(var(--muted-foreground))]">{t("versions.app")}</dt>
              <dd className="font-mono">{appVersion.data ?? "…"}</dd>
            </>
          )}
          <dt className="text-[hsl(var(--muted-foreground))]">
            {onServer ? `${t("versions.server")} (${connection?.server?.name ?? ""})` : t("versions.localCore")}
          </dt>
          <dd className="font-mono">{me.isError ? t("versions.unknown") : (me.data?.server_version ?? "…")}</dd>
        </dl>
      </CardContent>
    </Card>
  )
}
