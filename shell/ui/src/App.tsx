import { NavLink, Route, Routes } from "react-router-dom"
import { cn } from "@/lib/utils"
import { Library } from "@/pages/Library"
import { AnimeDetail } from "@/pages/AnimeDetail"
import { Folders } from "@/pages/Folders"
import { ReviewQueue } from "@/pages/ReviewQueue"
import { Settings } from "@/pages/Settings"
import { useLiveEvents } from "@/api/useLiveEvents"
import { AniDbBanBanner } from "@/components/AniDbBanBanner"
import { UpdateBanner } from "@/components/UpdateBanner"
import { useT } from "@/i18n/I18nContext"

function App() {
  useLiveEvents()
  const t = useT()

  const NAV_ITEMS = [
    { to: "/", label: t("nav.library"), end: true },
    { to: "/review", label: t("nav.review") },
    { to: "/folders", label: t("nav.folders") },
    { to: "/settings", label: t("nav.settings") },
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
                  "rounded-md px-3 py-1.5 text-sm",
                  isActive
                    ? "bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]"
                    : "text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <UpdateBanner />
      <AniDbBanBanner />
      <main className="flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/animes/:id" element={<AnimeDetail />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/folders" element={<Folders />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
