import type { AnySection } from './pages'

/** Rail groups of the new shell. Every existing section id appears exactly once, so old deep links
 *  (#/p/<id>/<section>) keep selecting the same panel. "Map" has no page yet and is shown disabled. */
export interface RailGroup {
  id: string
  label: string
  sections: AnySection[]
  /** No page behind it yet. */
  soon?: boolean
}

export const RAIL_GROUPS: RailGroup[] = [
  { id: 'home', label: 'Home', sections: ['overview'] },
  { id: 'map', label: 'Map', sections: [], soon: true },
  { id: 'build', label: 'Build', sections: ['model', 'machines', 'rules', 'hooks', 'settings', 'history', 'seed', 'documents'] },
  { id: 'secure', label: 'Secure', sections: ['auth', 'keycloak', 'access'] },
  { id: 'connect', label: 'Connect', sections: ['payments', 'storage', 'integrations'] },
  { id: 'operate', label: 'Operate', sections: ['observability'] },
  { id: 'ship', label: 'Ship', sections: ['deployment', 'generate'] },
]

export interface Command {
  id: string
  label: string
  hint: string
  run: () => void
}

/** Case-insensitive substring match on label and hint; every word must match. */
export function filterCommands(commands: Command[], query: string): Command[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return commands
  return commands.filter((c) => {
    const hay = `${c.label} ${c.hint}`.toLowerCase()
    return words.every((w) => hay.includes(w))
  })
}
