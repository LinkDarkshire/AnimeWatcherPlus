import { useState } from "react"
import { Link } from "react-router-dom"
import { useDownloadIntegrations, useWanted } from "@/api/hooks"
import type { DownloadRequestInfo, DownloadTarget, WantedAnime } from "@/api/types"
import { IntegrationsCard } from "@/components/downloads/IntegrationsCard"
import { SendPanel } from "@/components/downloads/SendPanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useT } from "@/i18n/I18nContext"

/** Which item's send panel is open: one at a time keeps the page calm. */
type OpenKey = string | null

const targetKey = (target: DownloadTarget) =>
  `${target.anime_id ?? ""}:${target.wishlist_entry_id ?? ""}:${target.episode ?? ""}`

export function Downloads() {
  const t = useT()
  const { data: wanted, isLoading } = useWanted()
  const { data: integrations } = useDownloadIntegrations()
  const [open, setOpen] = useState<OpenKey>(null)

  const toggle = (target: DownloadTarget) => {
    const key = targetKey(target)
    setOpen((current) => (current === key ? null : key))
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4">
      <div className="space-y-1">
        <h1 className="text-lg font-semibold">{t("downloads.title")}</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("downloads.description")}</p>
      </div>

      {/* Expanded until there's at least one integration -- that's when it's needed. */}
      <details open={integrations !== undefined && integrations.length === 0}>
        <summary className="cursor-pointer text-sm font-medium">{t("downloads.setupTitle")}</summary>
        <div className="pt-2">
          <IntegrationsCard />
        </div>
      </details>

      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("common.loading")}</p>}

      {wanted && (
        <>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold">{t("downloads.missingTitle", { count: wanted.missing.length })}</h2>
            {wanted.missing.length === 0 && (
              <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("downloads.nothingMissing")}</p>
            )}
            {wanted.missing.map((anime) => (
              <MissingAnimeCard key={anime.anime_id} anime={anime} open={open} onToggle={toggle} />
            ))}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold">{t("downloads.wishlistTitle", { count: wanted.wishlist.length })}</h2>
            {wanted.wishlist.length === 0 && (
              <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("downloads.nothingWished")}</p>
            )}
            {wanted.wishlist.map((item) => {
              const target = { wishlist_entry_id: item.entry_id }
              const details = [item.year, item.media_type].filter(Boolean).join(" · ")
              return (
                <Card key={item.entry_id}>
                  <CardContent className="space-y-2 p-3">
                    <WantedRow
                      label={item.title}
                      sublabel={[details, t("downloads.wholeSeries")].filter(Boolean).join(" · ")}
                      request={item.last_request}
                      isOpen={open === targetKey(target)}
                      onToggle={() => toggle(target)}
                    />
                    {open === targetKey(target) && <SendPanel target={target} />}
                  </CardContent>
                </Card>
              )
            })}
          </section>
        </>
      )}
    </div>
  )
}

function MissingAnimeCard({
  anime,
  open,
  onToggle,
}: {
  anime: WantedAnime
  open: OpenKey
  onToggle: (target: DownloadTarget) => void
}) {
  const t = useT()
  const [expanded, setExpanded] = useState(false)
  const details = [anime.year, anime.media_type].filter(Boolean).join(" · ")

  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <button type="button" className="min-w-0 text-left" onClick={() => setExpanded((v) => !v)}>
            <span className="mr-1 text-xs">{expanded ? "▾" : "▸"}</span>
            <span className="font-medium">{anime.title}</span>
            {details && <span className="ml-2 text-xs text-[hsl(var(--muted-foreground))]">{details}</span>}
          </button>
          <div className="flex shrink-0 items-center gap-2">
            <Badge variant="outline">{t("downloads.episodesMissing", { count: anime.episodes.length })}</Badge>
            <Link to={`/animes/${anime.anime_id}`} className="text-xs underline">
              →
            </Link>
          </div>
        </div>

        {expanded && (
          <div className="space-y-1.5 border-t pt-2">
            {anime.episodes.map((episode) => {
              const target = { anime_id: anime.anime_id, episode: Number(episode.ep_number) }
              const isOpen = open === targetKey(target)
              return (
                <div key={episode.ep_number} className="space-y-2">
                  <WantedRow
                    label={t("downloads.episode", { number: episode.ep_number })}
                    sublabel={[episode.title, episode.air_date && new Date(episode.air_date).toLocaleDateString()]
                      .filter(Boolean)
                      .join(" · ")}
                    request={episode.last_request}
                    isOpen={isOpen}
                    onToggle={() => onToggle(target)}
                  />
                  {isOpen && <SendPanel target={target} />}
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function WantedRow({
  label,
  sublabel,
  request,
  isOpen,
  onToggle,
}: {
  label: string
  sublabel: string
  request: DownloadRequestInfo | null
  isOpen: boolean
  onToggle: () => void
}) {
  const t = useT()
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <div className="min-w-0">
        <p className="truncate">{label}</p>
        <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">
          {sublabel}
          {request && (
            <span className="ml-1 text-emerald-600">
              {sublabel && "· "}
              {t("downloads.requested", {
                date: new Date(request.requested_at).toLocaleDateString(),
                client: request.client_name,
              })}
            </span>
          )}
        </p>
      </div>
      <Button size="sm" variant={isOpen ? "ghost" : "outline"} onClick={onToggle}>
        {isOpen ? t("downloads.close") : t("downloads.send")}
      </Button>
    </div>
  )
}
