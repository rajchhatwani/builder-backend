import { useEffect, useState, type ReactNode } from 'react'
import { useAuth } from './AuthProvider'

function getInitialTheme(): 'light' | 'dark' {
  const stored = localStorage.getItem('theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function useTheme() {
  const [theme, setTheme] = useState<'light' | 'dark'>(getInitialTheme)

  useEffect(() => {
    document.documentElement.style.colorScheme = theme
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  return { theme, toggle: () => setTheme((t) => (t === 'light' ? 'dark' : 'light')) }
}

interface LayoutProps {
  /** Navigation shown in the sidebar; it changes with the page. */
  sidebar: ReactNode
  children: ReactNode
}

export function Layout({ sidebar, children }: LayoutProps) {
  const { theme, toggle } = useTheme()
  const { state, signOut } = useAuth()
  const user = state.status === 'user' ? state.user : null

  return (
    <>
      <nav data-topnav>
        <div className="row">
          <div className="col-6 branding">
            <button data-sidebar-toggle aria-label="Toggle sidebar menu" className="small ghost">
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <line x1="4" y1="7" x2="20" y2="7" />
                <line x1="4" y1="12" x2="20" y2="12" />
                <line x1="4" y1="17" x2="16" y2="17" />
              </svg>
            </button>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
            </svg>
            <span>Backend Builder</span>
          </div>
          <div className="col-6 justify-end hstack">
            {user && (
              <>
                <a className="muted small-text" href="#/account" title="Account, password and API tokens">
                  {user.email}
                </a>
                {user.platform_role !== 'customer' && (
                  <a className="button outline small" href="#/admin">
                    Admin
                  </a>
                )}
                <button className="outline small" onClick={signOut}>
                  Sign out
                </button>
              </>
            )}
            <button className="outline small" onClick={toggle} aria-label="Toggle color theme">
              {theme === 'light' ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="5" />
                  <line x1="12" y1="1" x2="12" y2="3" />
                  <line x1="12" y1="21" x2="12" y2="23" />
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                  <line x1="1" y1="12" x2="3" y2="12" />
                  <line x1="21" y1="12" x2="23" y2="12" />
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </nav>

      <aside data-sidebar className="main-sidebar">
        {sidebar}
      </aside>

      <main>
        <div className="container">{children}</div>
      </main>
    </>
  )
}
