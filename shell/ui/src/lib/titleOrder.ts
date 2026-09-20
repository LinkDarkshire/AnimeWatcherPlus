import type { TranslationKey } from "@/i18n/translations"

/** The three title variants AniDB distinguishes. Mirrors TITLE_VARIANTS in
 * the Core's app/domain/titles.py -- these values are what gets stored. */
export const TITLE_VARIANTS = ["main", "en", "ja"] as const
export type TitleVariant = (typeof TITLE_VARIANTS)[number]

export const DEFAULT_TITLE_ORDER: TitleVariant[] = ["en", "main", "ja"]

export const TITLE_VARIANT_LABEL_KEYS: Record<TitleVariant, TranslationKey> = {
  main: "settings.titleVariantMain",
  en: "settings.titleVariantEn",
  ja: "settings.titleVariantJa",
}

function isTitleVariant(value: unknown): value is TitleVariant {
  return typeof value === "string" && (TITLE_VARIANTS as readonly string[]).includes(value)
}

/** Coerces a stored settings value into a complete, duplicate-free order.
 * Mirrors normalize_title_order on the Core side: the settings table is
 * free-form JSON, so what comes back can be partial, contain unknown entries,
 * or not be a list at all. */
export function normalizeTitleOrder(value: unknown): TitleVariant[] {
  const order: TitleVariant[] = []
  if (Array.isArray(value)) {
    for (const entry of value) {
      if (isTitleVariant(entry) && !order.includes(entry)) order.push(entry)
    }
  }
  for (const variant of DEFAULT_TITLE_ORDER) {
    if (!order.includes(variant)) order.push(variant)
  }
  return order
}

export function moveTitleVariant(order: TitleVariant[], from: number, to: number): TitleVariant[] {
  if (to < 0 || to >= order.length) return order
  const next = [...order]
  ;[next[from], next[to]] = [next[to], next[from]]
  return next
}
