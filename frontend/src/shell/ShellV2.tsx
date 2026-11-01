import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Organization, Project } from '../api/types'
import { useAuth } from '../components/AuthProvider'
import { useTheme } from '../components/Layout'
import { Icon, link, orgLabel, type Section } from '../components/Sidebar'
import { CommandPalette } from './CommandPalette'
import { RAIL_GROUPS, type Command } from './groups'
import { findSection, type AnySection } from './pages'
import { WorkbenchDrawer } from './workbench/WorkbenchDrawer'

interface Props {
  project: Project
  section: AnySection
  problems: Partial<Record<AnySection, number>>
  on?: Partial<Record<Section, boolean>>
  onShare?: () => void
  org?: Organization | null
  children: ReactNode
}

export const isPaletteKey = (e: Pick<KeyboardEvent, 'ctrlKey' | 'metaKey' | 'key'>) =>
  (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k'

/** True while any dialog (native <dialog open>, role=dialog or aria-modal) is on screen. */
export const anotherModalOpen = (doc: Document) =>
  doc.querySelector('dialog[open], [role="dialog"], [aria-modal="true"]') !== null

/** New shell (flag ui.shell=v2): top bar, grouped rail, Ctrl+K. Uses the same Oat page frame as the
 *  old Layout (nav[data-topnav], aside[data-sidebar], main); the old panels are mounted unchanged as children. */
export function ShellV2({ project, section, problems, on = {}, onShare, org, children }: Props) {
  const { theme, toggle } = useTheme()
  const { state, signOut } = useAuth()
  const user = state.status === 'user' ? state.user : null
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [workbenchOpen, setWorkbenchOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isPaletteKey(e)) {
        e.preventDefault()
        if (!e.repeat && !anotherModalOpen(document)) setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const commands = useMemo<Command[]>(() => {
    const go = (hash: string) => () => {
      window.location.hash = hash
    }
    const list: Command[] = []
    for (const g of RAIL_GROUPS) {
      for (const id of g.sections) {
        const s = findSection(id)
        if (s) list.push({ id: `s-${id}`, label: s.label, hint: g.label, run: go(`/p/${project.id}/${id}`) })
      }
    }
    list.push({ id: 'projects', label: 'All projects', hint: 'Go to', run: go('/') })
    if (org) list.push({ id: 'org', label: orgLabel(org), hint: 'Organization', run: go(`/org/${encodeURIComponent(org.slug)}`) })
    list.push({ id: 'account', label: 'Account', hint: 'Go to', run: go('/account') })
    if (user && user.platform_role !== 'customer') list.push({ id: 'admin', label: 'Admin console', hint: 'Go to', run: go('/admin') })
    list.push({ id: 'workbench', label: 'Workbench: API reference and request console', hint: 'Action', run: () => setWorkbenchOpen(true) })
    if (onShare) list.push({ id: 'share', label: 'Share project', hint: 'Action', run: onShare })
    list.push({ id: 'theme', label: 'Toggle color theme', hint: 'Action', run: toggle })
    list.push({ id: 'signout', label: 'Sign out', hint: 'Action', run: () => void signOut() })
    return list
  }, [project.id, org, user, onShare, toggle, signOut])

  return (
    <>
      <nav data-topnav data-shell="v2">
        <div className="row">
          <div className="col-6 branding">
            <button data-sidebar-toggle aria-label="Toggle sidebar menu" className="small ghost">
              <Icon>
                <line x1="4" y1="7" x2="20" y2="7" />
                <line x1="4" y1="12" x2="20" y2="12" />
                <line x1="4" y1="17" x2="16" y2="17" />
              </Icon>
            </button>
            <a href={link('/')} className="muted small-text" title="All projects">
              Projects
            </a>
            {org && (
              <a href={link(`/org/${encodeURIComponent(org.slug)}/projects`)} className="muted small-text" title="Organization">
                {orgLabel(org)}
              </a>
            )}
            <strong data-testid="shell-project">{project.name}</strong>
            {onShare && (
              <button className="ghost small" onClick={onShare} title="Who can access this project">
                Share
              </button>
            )}
          </div>
          <div className="col-6 justify-end hstack">
            <button className="outline small" onClick={() => setWorkbenchOpen((o) => !o)} aria-expanded={workbenchOpen} aria-controls="workbench-drawer" data-testid="workbench-toggle">
              Workbench
            </button>
            <button className="outline small" onClick={() => setPaletteOpen(true)} aria-haspopup="dialog">
              Search or jump to… <kbd>Ctrl+K</kbd>
            </button>
            {user && (
              <>
                <a className="muted small-text shell-email" href="#/account" title="Account, password and API tokens">
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
            <button className="outline small" onClick={toggle} title="Toggle color theme">
              {theme === 'light' ? 'Dark mode' : 'Light mode'}
            </button>
          </div>
        </div>
      </nav>

      <aside data-sidebar className="main-sidebar">
        <nav aria-label="Project">
          {RAIL_GROUPS.map((g) => {
            const items = g.sections.map((id) => findSection(id)!)
            const single = g.id === 'home'
            return (
              <div key={g.id} data-rail-group={g.id}>
                {!single && !g.soon && <p className="muted small-text sidebar-heading">{g.label}</p>}
                <ul>
                  {g.soon && (
                    <li>
                      <span className="rail-soon" aria-disabled="true">
                        {g.label} <span className="badge badge-muted">soon</span>
                      </span>
                    </li>
                  )}
                  {items.map((s) => (
                    <li key={s.id}>
                      <a href={link(`/p/${project.id}/${s.id}`)} aria-current={section === s.id ? 'page' : undefined}>
                        <Icon>{s.icon}</Icon>
                        <span>{single ? g.label : s.label}</span>
                        {!!problems[s.id] && <span className="count-badge">{problems[s.id]}</span>}
                        {!problems[s.id] && on[s.id as Section] && <span className="on-dot" title="On" />}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </nav>
      </aside>

      <main>
        <div className="container">{children}</div>
      </main>
      <WorkbenchDrawer key={project.id} projectId={project.id} open={workbenchOpen} onClose={() => setWorkbenchOpen(false)} />
      {paletteOpen && <CommandPalette commands={commands} onClose={() => setPaletteOpen(false)} />}
    </>
  )
}
