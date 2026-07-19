import type { IdentStatus } from "@/api/types"
import type { TranslationKey } from "@/i18n/translations"

export type BadgeVariant = "default" | "outline" | "destructive"

const VARIANT: Record<IdentStatus, BadgeVariant> = {
  identified: "default",
  pending: "outline",
  needs_manual_id: "destructive",
  review: "destructive",
}

const LABEL_KEY: Record<IdentStatus, TranslationKey> = {
  identified: "animeStatus.identified",
  pending: "animeStatus.pending",
  needs_manual_id: "animeStatus.needsManualId",
  review: "animeStatus.review",
}

export function getStatusVariant(status: IdentStatus): BadgeVariant {
  return VARIANT[status]
}

export function getStatusLabelKey(status: IdentStatus): TranslationKey {
  return LABEL_KEY[status]
}
