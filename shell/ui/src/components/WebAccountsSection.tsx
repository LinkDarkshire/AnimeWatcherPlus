import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, isWebUi } from "@/api/client"
import { useMe, useOnServer } from "@/api/shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

const muted = "text-xs text-[hsl(var(--muted-foreground))]"

interface WebAccount {
  id: number
  username: string
  is_admin: boolean
  created_at: string
  last_login_at: string | null
}

/** The web interface's logins: list, create, new password, delete. Admins
 * only, while the library is on a server. */
export function WebAccountsSection() {
  const t = useT()
  const queryClient = useQueryClient()
  const onServer = useOnServer()
  const me = useMe(onServer)
  const isAdmin = onServer && (me.data?.is_admin ?? false)
  const accounts = useQuery({
    queryKey: ["web-accounts"],
    queryFn: () => api.get<WebAccount[]>("/api/v1/web/accounts"),
    enabled: isAdmin,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["web-accounts"] })
  const create = useMutation({
    mutationFn: (account: { username: string; password: string; is_admin: boolean }) =>
      api.post<WebAccount>("/api/v1/web/accounts", account),
    onSuccess: () => {
      setUsername("")
      setPassword("")
      setAsAdmin(false)
    },
    onSettled: refresh,
  })
  const update = useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      api.patch<WebAccount>(`/api/v1/web/accounts/${id}`, { password }),
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.del<void>(`/api/v1/web/accounts/${id}`),
    onSettled: refresh,
  })
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [asAdmin, setAsAdmin] = useState(false)

  if (!isAdmin) return null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate({ username, password, is_admin: asAdmin })
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <p className="text-sm font-medium">{t("web.accountsTitle")}</p>
        <p className={muted}>{t("web.accountsDescription")}</p>
        {accounts.data?.length === 0 && <p className={muted}>{t("web.noAccounts")}</p>}
        <ul className="divide-y divide-[hsl(var(--border))]">
          {accounts.data?.map((account) => (
            <li key={account.id} className="flex flex-wrap items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm">
                  {account.username}
                  {account.username === me.data?.web_username && (
                    <span className={`ml-2 ${muted}`}>{t("web.you")}</span>
                  )}
                </p>
                <p className={muted}>
                  {account.last_login_at
                    ? t("web.lastLogin", { date: new Date(account.last_login_at).toLocaleString() })
                    : t("web.neverLoggedIn")}
                </p>
              </div>
              {account.is_admin && <Badge>{t("web.admin")}</Badge>}
              <Button
                size="sm"
                variant="outline"
                disabled={update.isPending}
                onClick={() => {
                  const next = prompt(t("web.newPasswordPrompt", { name: account.username }))
                  if (next) update.mutate({ id: account.id, password: next })
                }}
              >
                {t("web.setPassword")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={remove.isPending}
                onClick={() => {
                  if (confirm(t("web.deleteConfirm", { name: account.username }))) remove.mutate(account.id)
                }}
              >
                {t("web.delete")}
              </Button>
            </li>
          ))}
        </ul>
        <form onSubmit={submit} className="space-y-2 rounded-md border border-[hsl(var(--border))] p-3">
          <p className="text-sm font-medium">{t("web.newAccount")}</p>
          <div className="flex flex-wrap gap-2">
            <Input
              className="w-44"
              placeholder={t("web.username")}
              autoComplete="off"
              autoCapitalize="none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <Input
              className="w-44"
              type="password"
              placeholder={t("web.password")}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Button type="submit" size="sm" disabled={create.isPending || !username || password.length < 8}>
              {t("web.create")}
            </Button>
          </div>
          <p className={muted}>{t("web.passwordHint")}</p>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={asAdmin} onChange={(e) => setAsAdmin(e.target.checked)} />
            {t("web.makeAdmin")}
          </label>
        </form>
      </CardContent>
    </Card>
  )
}

/** In the web interface: who is signed in, own password, sign out. */
export function WebSessionSection() {
  const t = useT()
  const me = useMe(isWebUi())
  const [current, setCurrent] = useState("")
  const [next, setNext] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const change = useMutation({
    mutationFn: () => api.put<void>("/api/v1/web/password", { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent("")
      setNext("")
      setMessage(t("web.passwordChanged"))
    },
  })

  if (!isWebUi() || !me.data?.web_username) return null

  const logout = async () => {
    await api.post<void>("/api/v1/web/logout")
    window.location.reload()
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center gap-3">
          <p className="flex-1 text-sm font-medium">{t("web.signedInAs", { name: me.data.web_username })}</p>
          <Button size="sm" variant="outline" onClick={logout}>
            {t("web.logout")}
          </Button>
        </div>
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault()
            setMessage(null)
            change.mutate()
          }}
        >
          <p className="text-sm">{t("web.changeOwnPassword")}</p>
          <div className="flex flex-wrap gap-2">
            <Input
              className="w-44"
              type="password"
              placeholder={t("web.currentPassword")}
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
            <Input
              className="w-44"
              type="password"
              placeholder={t("web.newPassword")}
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <Button type="submit" size="sm" disabled={change.isPending || !current || next.length < 8}>
              {t("web.save")}
            </Button>
          </div>
          {message && <p className={muted}>{message}</p>}
        </form>
      </CardContent>
    </Card>
  )
}
