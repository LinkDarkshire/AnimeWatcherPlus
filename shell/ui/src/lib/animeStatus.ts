import type { IdentStatus } from "@/api/types"

export type BadgeVariant = "default" | "outline" | "destructive"

export interface StatusPresentation {
  label: string
  variant: BadgeVariant
}

const PRESENTATION: Record<IdentStatus, StatusPresentation> = {
  identified: { label: "Identifiziert", variant: "default" },
  pending: { label: "Wird verarbeitet…", variant: "outline" },
  needs_manual_id: { label: "Unidentifiziert", variant: "destructive" },
  review: { label: "Review nötig", variant: "destructive" },
}

export function getStatusPresentation(status: IdentStatus): StatusPresentation {
  return PRESENTATION[status]
}
