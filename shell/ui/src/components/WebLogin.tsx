import { useState, type FormEvent } from "react"
import { api } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

const muted = "text-sm text-[hsl(var(--muted-foreground))]"

/** The web interface's login page. */
export function WebLogin({ onDone }: { onDone: () => void }) {
  const t = useT()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post<void>("/api/v1/web/login", { username, password })
      setPassword("")
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">AnimeWatcherPlus</h1>
          <p className={muted}>{t("web.loginDescription")}</p>
        </div>
        <label className="block space-y-1">
          <span className="text-sm">{t("web.username")}</span>
          <Input
            autoComplete="username"
            autoCapitalize="none"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </label>
        <label className="block space-y-1">
          <span className="text-sm">{t("web.password")}</span>
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="text-sm text-red-500">{error}</p>}
        <Button type="submit" className="w-full" disabled={busy || !username || !password}>
          {t("web.login")}
        </Button>
      </form>
    </div>
  )
}
