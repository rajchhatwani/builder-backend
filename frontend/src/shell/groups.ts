import type { AnySection } from './pages'

/** Rail groups of the new shell. Every existing section id appears exactly once, so old deep links
 *  (#/p/<id>/<section>) keep selecting the same panel. */
export interface RailGroup {
  id: string
  label: string
  sections: AnySection[]
  /** No page behind it yet. */
  soon?: boolean
}

export const RAIL_GROUPS: RailGroup[] = [
  { id: 'home', label: 'Home', sections: ['overview'] },
  { id: 'ai', label: 'Build with AI', sections: ['intake', 'plan', 'build', 'approvals', 'see'] },
  { id: 'build', label: 'Build', sections: ['model', 'machines', 'rules', 'permissions', 'specdiff', 'hooks', 'settings', 'history', 'timeline', 'seed', 'customfields', 'events', 'hookeffects'] },
  { id: 'secure', label: 'Secure', sections: ['auth', 'keycloak', 'suite', 'access', 'dependencies', 'compliance'] },
  { id: 'connect', label: 'Connect', sections: ['payments', 'storage', 'integrations', 'forms', 'notifications', 'notiftypes', 'webhooks', 'providers', 'apiedge', 'import', 'apikeys', 'apps', 'ledgersettings', 'currencysettings', 'reconsettings', 'invoicingsettings', 'bookingsettings', 'geosettings', 'locationsettings', 'matchingsettings', 'predictionsettings', 'aigatewaysettings', 'aidocssettings', 'knowledgesettings', 'agentssettings', 'evalssettings'] },
  { id: 'operate', label: 'Operate', sections: ['observability', 'jobs', 'workers', 'workflows', 'traces', 'metrics', 'search', 'ledger', 'invoices', 'payouts', 'reconciliation', 'map', 'bookings', 'bookingadmin', 'documents', 'agentactions', 'places', 'matching', 'prediction', 'routing', 'aiusage', 'knowledge', 'evals', 'agentruns'] },
  { id: 'ship', label: 'Ship', sections: ['deployment', 'generate', 'upgrades'] },
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
