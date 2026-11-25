import { createContext, useContext, useLayoutEffect, useState } from 'react'
import type { ReactNode } from 'react'
import en from './locales/en.json'

const catalogs = { en }
type Language = keyof typeof catalogs
type Catalog = { [key: string]: string | Catalog }
type Variables = Record<string, string | number>
type Translate = (key: string, variables?: Variables) => string
const fallback: Language = 'en'
const storageKey = 'v2-language'
const suggestionKey = 'v2-language-suggestion-seen'

function storageRead(key: string) {
  try { return localStorage.getItem(key) } catch { return null }
}

function storageWrite(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* Storage may be unavailable. */ }
}

function supported(tag: string): Language | undefined {
  const normalized = tag.toLowerCase()
  return ([normalized, normalized.split('-')[0]]).find(code => Object.hasOwn(catalogs, code)) as Language | undefined
}

export function detectLanguage(saved: string | null, browserLanguages: readonly string[]) {
  const chosen = saved && supported(saved)
  if (chosen) return { language: chosen, source: 'saved' } as const
  const language = browserLanguages.map(supported).find(Boolean)
  return language ? { language, source: 'browser' } as const : { language: fallback, source: 'fallback' } as const
}

function lookup(catalog: Catalog, key: string): string | undefined {
  let value: Catalog | string = catalog
  for (const part of key.split('.')) {
    if (typeof value !== 'object' || !Object.hasOwn(value, part)) return undefined
    value = value[part]
  }
  return typeof value === 'string' ? value : undefined
}

function translator(language: Language, routeEnglish?: Catalog): Translate {
  return (key, variables = {}) => {
    const count = variables.count
    const plural = typeof count === 'number' ? `${key}_${new Intl.PluralRules(language).select(count)}` : key
    const text = lookup(catalogs[language], plural) ?? lookup(catalogs[language], key) ??
      lookup(en, plural) ?? lookup(en, key) ??
      (routeEnglish && (lookup(routeEnglish, plural) ?? lookup(routeEnglish, key))) ?? key
    return text.replace(/{{\s*(\w+)\s*}}/g, (_, name: string) => {
      const value = variables[name]
      return typeof value === 'number' ? new Intl.NumberFormat(language).format(value) : value ?? ''
    })
  }
}

const LanguageContext = createContext({
  language: fallback,
  dir: 'ltr' as 'ltr' | 'rtl',
  t: translator(fallback),
  choose: (_language: Language) => {},
  suggest: false,
  dismissSuggestion: () => {},
})

export function I18nProvider({ children }: { children: ReactNode }) {
  const [choice, setChoice] = useState(() => detectLanguage(storageRead(storageKey), navigator.languages))
  const [seen, setSeen] = useState(() => storageRead(suggestionKey) === 'true')
  const { language } = choice
  const dir = /^(ar|fa|he|ur)(-|$)/.test(language) ? 'rtl' : 'ltr'

  useLayoutEffect(() => {
    document.documentElement.lang = language
    document.documentElement.dir = dir
    document.title = translator(language)('shell.product')
  }, [language, dir])

  return (
    <LanguageContext.Provider value={{
      language, dir, t: translator(language),
      suggest: choice.source === 'browser' && !seen,
      dismissSuggestion: () => { storageWrite(suggestionKey, 'true'); setSeen(true) },
      choose: (language) => { storageWrite(storageKey, language); setChoice({ language, source: 'saved' }) },
    }}>
      {children}
    </LanguageContext.Provider>
  )
}

export function useLanguage() { return useContext(LanguageContext) }
export function useT() { return useLanguage().t }

export function RouteTranslations({ english, children }: { english: Catalog; children: ReactNode }) {
  const value = useLanguage()
  return <LanguageContext.Provider value={{ ...value, t: translator(value.language, english) }}>
    {children}
  </LanguageContext.Provider>
}
