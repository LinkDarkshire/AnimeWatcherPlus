import { useState } from "react"
import { NavLink, Route, Routes, useLocation } from "react-router-dom"
import {
  ClipboardCheck,
  Download,
  Ellipsis,
  Folder,
  Library,
  ListX,
  Settings2,
  Star,
  type LucideIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Library as LibraryPage } from "@/pages/Library"
import { AnimeDetail } from "@/pages/AnimeDetail"
import { MissingEpisodes } from "@/pages/MissingEpisodes"
import { Folders } from "@/pages/Folders"
import { ReviewQueue } from "@/pages/ReviewQueue"
import { Settings } from "@/pages/Settings"
import { Wishlist } from "@/pages/Wishlist"
import { Downloads } from "@/pages/Downloads"
import { useLiveEvents } from "@/api/useLiveEvents"
import { shell, useShellConnection } from "@/api/shell"
import { MobileOnboarding } from "@/components/MobileOnboarding"
import { ServerStatusBanner } from "@/components/ServerStatusBanner"
import { useSharedText } from "@/lib/useSharedText"
import { usePendingActionsCount } from "@/api/hooks"
import { AniDbActivity } from "@/components/AniDbActivity"
import { AniDbBanBanner } from "@/components/AniDbBanBanner"
import { EmptyFolderPrompt } from "@/components/EmptyFolderPrompt"
import { ErrorToasts } from "@/components/ErrorToasts"
import { Badge } from "@/components/ui/badge"
import * as DialogPrimitive from "@radix-ui/react-dialog"
import { useT } from "@/i18n/I18nContext"

interface NavItem {
  to: string
  label: string
  /** For the phone's tab bar, where the full label doesn't fit. */
  short?: string
  end: boolean
  badge: number
  icon: LucideIcon
  /** In the phone's bottom bar; the rest goes into "More". */
  primary: boolean
}

function App() {
  const { data: connection, isPending } = useShellConnection()
  // In the app, wait for the shell to say where the data is.
  if (shell.available() && isPending) return null
  // A phone without a server has nothing to show but pairing.
  if (connection?.platform === "mobile" && !connection.server) return <MobileOnboarding />
  return <MainApp mobile={connection?.platform === "mobile"} />
}

function MainApp({ mobile }: { mobile: boolean }) {
  useLiveEvents()
  useSharedText(mobile)
  const t = useT()
  const { data: pendingActions } = usePendingActionsCount()
  const pendingCount = pendingActions?.total ?? 0
  const [moreOpen, setMoreOpen] = useState(false)
  const location = useLocation()

  const NAV_ITEMS: NavItem[] = [
    { to: "/", label: t("nav.library"), end: true, badge: 0, icon: Library, primary: true },
    { to: "/missing-episodes", label: t("nav.missingEpisodes"), short: t("nav.missingShort"), end: false, badge: 0, icon: ListX, primary: true },
    { to: "/wishlist", label: t("nav.wishlist"), end: false, badge: 0, icon: Star, primary: true },
    { to: "/downloads", label: t("nav.downloads"), end: false, badge: 0, icon: Download, primary: true },
    { to: "/review", label: t("nav.review"), end: false, badge: pendingCount, icon: ClipboardCheck, primary: false },
    { to: "/folders", label: t("nav.folders"), end: false, badge: 0, icon: Folder, primary: false },
    { to: "/settings", label: t("nav.settings"), end: false, badge: 0, icon: Settings2, primary: false },
  ]
  const secondary = NAV_ITEMS.filter((item) => !item.primary)
  const secondaryActive = secondary.some((item) => location.pathname.startsWith(item.to))
  const secondaryBadge = secondary.reduce((sum, item) => sum + item.badge, 0)

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-4 border-b px-4 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
        <span className="shrink-0 font-semibold">AnimeWatcherPlus</span>
        <nav className="hidden gap-1 lg:flex">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm",
                  isActive
                    ? "bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]"
                    : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]",
                )
              }
            >
              {item.label}
              {item.badge > 0 && <Badge variant="destructive">{item.badge}</Badge>}
            </NavLink>
          ))}
        </nav>
        <AniDbActivity />
      </header>
      <ServerStatusBanner />
      <AniDbBanBanner />
      <EmptyFolderPrompt />
      <main className="flex-1 overflow-x-hidden overflow-y-auto">
        <Routes>
          <Route path="/" element={<LibraryPage />} />
          <Route path="/animes/:id" element={<AnimeDetail />} />
          <Route path="/missing-episodes" element={<MissingEpisodes />} />
          <Route path="/wishlist" element={<Wishlist />} />
          <Route path="/downloads" element={<Downloads />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/folders" element={<Folders />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>

      {/* Phones and tablets: the main pages as a tab bar, the rest under "More". */}
      <nav className="grid grid-cols-5 border-t pb-[env(safe-area-inset-bottom)] lg:hidden">
        {NAV_ITEMS.filter((item) => item.primary).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => cn(tabClass, isActive && tabActiveClass)}
          >
            <item.icon className="h-5 w-5" />
            <span className="max-w-full truncate">{item.short ?? item.label}</span>
          </NavLink>
        ))}
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          className={cn(tabClass, "relative", secondaryActive && tabActiveClass)}
        >
          <Ellipsis className="h-5 w-5" />
          <span>{t("nav.more")}</span>
          {secondaryBadge > 0 && (
            <span className="absolute top-0.5 left-[calc(50%+0.5rem)] rounded-full bg-[hsl(var(--destructive))] px-1.5 text-[10px] leading-4 text-[hsl(var(--destructive-foreground))]">
              {secondaryBadge}
            </span>
          )}
        </button>
      </nav>
      <DialogPrimitive.Root open={moreOpen} onOpenChange={setMoreOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 lg:hidden" />
          <DialogPrimitive.Content
            aria-describedby={undefined}
            className="fixed inset-x-0 bottom-0 z-50 rounded-t-lg border-t bg-[hsl(var(--card))] p-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-[hsl(var(--card-foreground))] lg:hidden"
          >
          <DialogPrimitive.Title className="sr-only">{t("nav.more")}</DialogPrimitive.Title>
          <div className="flex flex-col gap-1">
            {secondary.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setMoreOpen(false)}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-md px-3 py-3 text-sm",
                    isActive ? "bg-[hsl(var(--accent))]" : "hover:bg-[hsl(var(--accent))]",
                  )
                }
              >
                <item.icon className="h-5 w-5" />
                <span className="flex-1">{item.label}</span>
                {item.badge > 0 && <Badge variant="destructive">{item.badge}</Badge>}
              </NavLink>
            ))}
          </div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
      <ErrorToasts />
    </div>
  )
}

const tabClass =
  "flex min-w-0 flex-col items-center gap-0.5 px-1 py-1.5 text-[11px] text-[hsl(var(--muted-foreground))]"
const tabActiveClass = "text-[hsl(var(--foreground))]"

export default App
