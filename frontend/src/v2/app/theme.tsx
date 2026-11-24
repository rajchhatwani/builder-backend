import { createContext, useContext, useLayoutEffect, useState } from 'react'
import type { ReactNode } from 'react'

type Theme = 'light' | 'dark'
const preference = '(prefers-color-scheme: dark)'
const ThemeContext = createContext<{ theme: Theme; choose: (theme: Theme) => void }>({ theme: 'light', choose: () => {} })

function storedTheme(): Theme | undefined {
  try {
    const value = localStorage.getItem('theme')
    return value === 'light' || value === 'dark' ? value : undefined
  } catch {
    return undefined
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoice] = useState(storedTheme)
  const [system, setSystem] = useState<Theme>(() => matchMedia(preference).matches ? 'dark' : 'light')
  const theme = choice ?? system

  useLayoutEffect(() => {
    const media = matchMedia(preference)
    const sync = () => setSystem(media.matches ? 'dark' : 'light')
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [])

  useLayoutEffect(() => { document.documentElement.dataset.theme = theme }, [theme])

  return (
    <ThemeContext.Provider value={{ theme, choose: next => {
      try { localStorage.setItem('theme', next) } catch { /* Storage may be unavailable. */ }
      setChoice(next)
    } }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() { return useContext(ThemeContext) }
