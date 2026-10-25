import { useId, useState } from "react"
import type { TagSummary } from "@/api/types"
import { Input } from "@/components/ui/input"
import { useT } from "@/i18n/I18nContext"

/** Filtering by several tags at once: type to pick from the known tags,
 * each picked one becomes a chip. The library shows anime that have every
 * picked tag. */
export function TagFilter({
  tags,
  selected,
  onChange,
}: {
  tags: TagSummary[]
  selected: string[]
  onChange: (tags: string[]) => void
}) {
  const t = useT()
  const listId = useId()
  const [input, setInput] = useState("")

  const add = (raw: string) => {
    const match = tags.find((tag) => tag.name.toLowerCase() === raw.trim().toLowerCase())
    if (!match) return false
    if (!selected.includes(match.name)) onChange([...selected, match.name])
    setInput("")
    return true
  }

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {selected.map((name) => (
        <span
          key={name}
          className="inline-flex items-center gap-1 rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--accent))] py-0.5 pr-1 pl-2.5 text-xs"
        >
          {name}
          <button
            type="button"
            aria-label={t("library.removeTag", { tag: name })}
            className="rounded-full px-1 hover:bg-[hsl(var(--background))]"
            onClick={() => onChange(selected.filter((s) => s !== name))}
          >
            ✕
          </button>
        </span>
      ))}
      <Input
        list={listId}
        value={input}
        placeholder={selected.length ? t("library.addTag") : t("library.tagsPlaceholder")}
        className="w-44"
        onChange={(e) => {
          // Picking from the suggestions sets the full name at once.
          if (!add(e.target.value)) setInput(e.target.value)
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            add(input)
          } else if (e.key === "Backspace" && !input && selected.length) {
            onChange(selected.slice(0, -1))
          }
        }}
      />
      <datalist id={listId}>
        {tags
          .filter((tag) => !selected.includes(tag.name))
          .map((tag) => (
            <option key={tag.id} value={tag.name}>
              {tag.anime_count}
            </option>
          ))}
      </datalist>
      {selected.length > 1 && (
        <button type="button" className="text-xs underline" onClick={() => onChange([])}>
          {t("library.clearTags")}
        </button>
      )}
    </div>
  )
}
