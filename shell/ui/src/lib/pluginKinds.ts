import type { DownloadPluginKind } from "@/api/types"
import type { TranslationKey } from "@/i18n/translations"

export const KIND_LABELS: Record<DownloadPluginKind, TranslationKey> = {
  client: "downloads.kindClient",
  source: "downloads.kindSource",
  resolver: "downloads.kindResolver",
}
