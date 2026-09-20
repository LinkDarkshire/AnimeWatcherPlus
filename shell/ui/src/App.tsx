import { NavLink, Route, Routes } from "react-router-dom"
import { cn } from "@/lib/utils"
import { Library } from "@/pages/Library"
import { AnimeDetail } from "@/pages/AnimeDetail"
import { MissingEpisodes } from "@/pages/MissingEpisodes"
import { Folders } from "@/pages/Folders"
import { ReviewQueue } from "@/pages/ReviewQueue"
import { Settings } from "@/pages/Settings"
import { useLiveEvents } from "@/api/useLiveEvents"
import { usePendingActionsCount } from "@/api/hooks"
import { AniDbBanBanner } from "@/components/AniDbBanBanner"
import { EmptyFolderPrompt } from "@/components/EmptyFolderPrompt"
import { Badge } from "@/components/ui/badge"
import { useT } from "@/i18n/I18nContext"

function App() {
  useLiveEvents()
  const t = useT()
  const { data: pendingActions } = usePendingActionsCount()
  const pendingCount = pendingActions?.total ?? 0

  const NAV_ITEMS = [
    { to: "/", label: t("nav.library"), end: true, badge: 0 },
    { to: "/missing-episodes", label: t("nav.missingEpisodes"), end: false, badge: 0 },
    { to: "/review", label: t("nav.review"), end: false, badge: pendingCount },
    { to: "/folders", label: t("nav.folders"), end: false, badge: 0 },
    { to: "/settings", label: t("nav.settings"), end: false, badge: 0 },
  ]

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-4 border-b px-4 py-2">
        <span className="font-semibold">AnimeWatcherPlus</span>
        <nav className="flex gap-1">
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
      </header>
      <AniDbBanBanner />
      <EmptyFolderPrompt />
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/animes/:id" element={<AnimeDetail />} />
          <Route path="/missing-episodes" element={<MissingEpisodes />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/folders" element={<Folders />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
