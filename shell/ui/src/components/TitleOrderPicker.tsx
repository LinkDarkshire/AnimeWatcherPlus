import { Button } from "@/components/ui/button"
import { useT } from "@/i18n/I18nContext"
import { TITLE_VARIANT_LABEL_KEYS, moveTitleVariant, type TitleVariant } from "@/lib/titleOrder"

type Props = {
  label: string
  hint?: string
  value: TitleVariant[]
  disabled?: boolean
  onChange: (next: TitleVariant[]) => void
}

/** Ranked list of the AniDB title variants: the first one an anime actually
 * has is the name that gets used. */
export function TitleOrderPicker({ label, hint, value, disabled, onChange }: Props) {
  const t = useT()

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{label}</p>
      {hint && <p className="text-xs text-[hsl(var(--muted-foreground))]">{hint}</p>}
      <ol className="space-y-1">
        {value.map((variant, index) => (
          <li
            key={variant}
            className="flex items-center gap-2 rounded-md border border-[hsl(var(--border))] px-2 py-1.5 text-sm"
          >
            <span className="w-4 shrink-0 text-[hsl(var(--muted-foreground))]">{index + 1}.</span>
            <span className="flex-1">{t(TITLE_VARIANT_LABEL_KEYS[variant])}</span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("settings.titleOrderMoveUp")}
              title={t("settings.titleOrderMoveUp")}
              disabled={disabled || index === 0}
              onClick={() => onChange(moveTitleVariant(value, index, index - 1))}
            >
              ↑
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("settings.titleOrderMoveDown")}
              title={t("settings.titleOrderMoveDown")}
              disabled={disabled || index === value.length - 1}
              onClick={() => onChange(moveTitleVariant(value, index, index + 1))}
            >
              ↓
            </Button>
          </li>
        ))}
      </ol>
    </div>
  )
}
