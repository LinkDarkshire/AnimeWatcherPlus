import { useState, type FormEvent } from "react"
import {
  useCreateFolder,
  useDeleteFolder,
  useFolders,
  useRescanFolder,
} from "@/api/hooks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

export function Folders() {
  const { data: folders, isLoading } = useFolders()
  const createFolder = useCreateFolder()
  const deleteFolder = useDeleteFolder()
  const rescanFolder = useRescanFolder()

  const [path, setPath] = useState("")
  const [type, setType] = useState<"content" | "download">("content")
  const [name, setName] = useState("")
  const [formError, setFormError] = useState<string | null>(null)

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setFormError(null)
    createFolder.mutate(
      { path, type, name: name || undefined },
      {
        onSuccess: () => {
          setPath("")
          setName("")
        },
        onError: (err) => setFormError(err instanceof Error ? err.message : "Fehler beim Anlegen"),
      },
    )
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-4">
      <h1 className="text-lg font-semibold">Ordner</h1>

      <form onSubmit={handleSubmit} className="space-y-2 rounded-lg border p-4">
        <div className="flex gap-2">
          <Input
            placeholder="Absoluter Pfad, z.B. D:/Anime/Content"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            className="flex-1"
          />
          <select
            value={type}
            onChange={(e) => setType(e.target.value as "content" | "download")}
            className="h-9 rounded-md border border-[hsl(var(--border))] bg-transparent px-2 text-sm"
          >
            <option value="content">Content</option>
            <option value="download">Download</option>
          </select>
        </div>
        <Input placeholder="Anzeigename (optional)" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" disabled={!path || createFolder.isPending}>
          Ordner hinzufügen
        </Button>
        {formError && <p className="text-sm text-red-500">{formError}</p>}
      </form>

      {isLoading && <p className="text-sm text-[hsl(var(--muted-foreground))]">Lädt…</p>}

      <div className="space-y-2">
        {folders?.map((folder) => (
          <Card key={folder.id}>
            <CardContent className="flex items-center justify-between gap-2 p-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{folder.name}</p>
                <p className="truncate text-xs text-[hsl(var(--muted-foreground))]">{folder.path}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Badge variant="outline">{folder.type === "content" ? "Content" : "Download"}</Badge>
                {folder.offline && <Badge variant="destructive">Offline</Badge>}
                <Button size="sm" variant="outline" onClick={() => rescanFolder.mutate(folder.id)}>
                  Rescan
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => {
                    if (confirm(`Ordner "${folder.name}" wirklich entfernen?`)) {
                      deleteFolder.mutate(folder.id)
                    }
                  }}
                >
                  Entfernen
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
