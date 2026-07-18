import { useState } from "react"
import { Link } from "react-router-dom"
import { useIdentifyAnime, useReviewQueue } from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

export function ReviewQueue() {
  const { data: items, isLoading } = useReviewQueue()
  const identify = useIdentifyAnime()
  const [manualIds, setManualIds] = useState<Record<number, string>>({})

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <h1 className="text-lg font-semibold">Unidentifiziert / Review</h1>
      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">Lädt…</p>}
      {items?.length === 0 && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">Nichts zu überprüfen.</p>
      )}

      <div className="space-y-3">
        {items?.map((item) => (
          <Card key={item.anime_id}>
            <CardContent className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Link to={`/animes/${item.anime_id}`} className="font-medium hover:underline">
                    {item.title_guess}
                  </Link>
                  <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">
                    {item.directory_path}
                  </p>
                </div>
                <Badge variant={item.ident_status === "review" ? "outline" : "destructive"}>
                  {item.ident_status === "review" ? "Review" : "Keine ID"}
                </Badge>
              </div>

              {item.candidates && item.candidates.length > 0 && (
                <div className="space-y-1.5">
                  {item.candidates.map((c) => (
                    <div key={c.aid} className="flex items-center justify-between rounded border p-2 text-sm">
                      <span>
                        {c.title}{" "}
                        <span className="text-[hsl(var(--muted-foreground))]">
                          (AID {c.aid}, Score {c.score.toFixed(0)})
                        </span>
                      </span>
                      <Button
                        size="sm"
                        onClick={() => identify.mutate({ animeId: item.anime_id, anidbId: c.aid })}
                      >
                        Übernehmen
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-center gap-2">
                <Input
                  placeholder="AniDB-ID manuell eingeben"
                  value={manualIds[item.anime_id] ?? ""}
                  onChange={(e) =>
                    setManualIds((prev) => ({ ...prev, [item.anime_id]: e.target.value }))
                  }
                  className="max-w-[200px]"
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!manualIds[item.anime_id]}
                  onClick={() =>
                    identify.mutate({
                      animeId: item.anime_id,
                      anidbId: Number(manualIds[item.anime_id]),
                    })
                  }
                >
                  Zuweisen
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
