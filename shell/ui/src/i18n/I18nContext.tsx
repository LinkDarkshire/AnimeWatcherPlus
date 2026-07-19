import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react"
import { useSettings, useUpdateSettings } from "@/api/hooks"
import { interpolate, translations, type Language, type TranslationKey } from "./translations"

const UI_LANGUAGE_KEY = "ui_language"
const DEFAULT_LANGUAGE: Language = "de"

interface I18nContextValue {
  language: Language
  setLanguage: (language: Language) => void
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function resolveLanguage(stored: unknown): Language {
  return typeof stored === "string" && stored in translations ? (stored as Language) : DEFAULT_LANGUAGE
}

/** Persists the chosen UI language through the same generic key/value
 * Setting store the staleness-rescan settings already use (PUT /api/v1/settings)
 * -- no dedicated backend endpoint needed. */
export function I18nProvider({ children }: { children: ReactNode }) {
  const { data: settings } = useSettings()
  const updateSettings = useUpdateSettings()
  const language = resolveLanguage(settings?.values[UI_LANGUAGE_KEY])

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  const value = useMemo<I18nContextValue>(() => {
    const dict = translations[language]
    return {
      language,
      setLanguage: (next) => updateSettings.mutate({ [UI_LANGUAGE_KEY]: next }),
      t: (key, vars) => interpolate(dict[key], vars),
    }
  }, [language, updateSettings])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

function useI18nContext(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error("useT/useLanguage must be used within I18nProvider")
  return ctx
}

export function useT() {
  return useI18nContext().t
}

export function useLanguage() {
  const { language, setLanguage } = useI18nContext()
  return { language, setLanguage }
}
