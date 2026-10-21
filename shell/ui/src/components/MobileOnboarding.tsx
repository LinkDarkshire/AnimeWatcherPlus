import { PairWizard } from "@/components/PairWizard"
import { useT } from "@/i18n/I18nContext"

/** A phone has no library of its own: until it's paired with a server,
 * pairing is all there is. */
export function MobileOnboarding() {
  const t = useT()
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 p-4 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))]">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">AnimeWatcherPlus</h1>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">{t("dataSource.mobileIntro")}</p>
      </div>
      {/* The proxy picks up the new pairing right away; a reload starts the app with it. */}
      <PairWizard canScan onDone={() => window.location.reload()} />
    </div>
  )
}
