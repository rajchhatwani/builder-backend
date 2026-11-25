/** URL contract shared by the application router and project screens. */
export const guidedSections = ['intake', 'plan', 'build', 'approvals', 'see'] as const
export const advancedGroups = [
  { id: 'home', sections: ['overview', 'code'] },
  { id: 'build', sections: ['model', 'machines', 'rules', 'permissions', 'specdiff', 'hooks', 'settings', 'history', 'timeline', 'seed', 'customfields', 'events', 'hookeffects'] },
  { id: 'secure', sections: ['auth', 'keycloak', 'suite', 'access', 'dependencies', 'compliance'] },
  { id: 'connect', sections: ['payments', 'storage', 'integrations', 'forms', 'notifications', 'notiftypes', 'webhooks', 'providers', 'apiedge', 'import', 'apikeys', 'apps',
    'ledgersettings', 'currencysettings', 'reconsettings', 'invoicingsettings', 'bookingsettings', 'geosettings', 'locationsettings',
    'matchingsettings', 'predictionsettings', 'aigatewaysettings', 'aidocssettings', 'knowledgesettings', 'agentssettings', 'evalssettings'] },
  { id: 'operate', sections: ['observability', 'jobs', 'workers', 'workflows', 'traces', 'logs', 'metrics', 'search', 'ledger', 'invoices', 'payouts', 'reconciliation', 'map',
    'bookings', 'bookingadmin', 'documents', 'agentactions', 'places', 'matching', 'prediction', 'routing', 'aiusage', 'knowledge', 'evals', 'agentruns'] },
  { id: 'ship', sections: ['deployment', 'generate', 'upgrades'] },
  { id: 'diagrams', sections: ['diagrams'] },
] as const

export const behaviorSections = ['hooks', 'hookeffects', 'events', 'settings', 'seed', 'customfields'] as const
export const isBehaviorSection = (section: string): section is typeof behaviorSections[number] =>
  behaviorSections.some(name => name === section)

const secureSections = ['auth', 'keycloak', 'suite', 'access', 'dependencies', 'compliance'] as const
export const isSecureSection = (section: string): section is typeof secureSections[number] =>
  secureSections.some(name => name === section)

export const packSections = ['ledgersettings', 'currencysettings', 'reconsettings', 'invoicingsettings', 'bookingsettings', 'geosettings', 'locationsettings',
  'matchingsettings', 'predictionsettings', 'aigatewaysettings', 'aidocssettings', 'knowledgesettings', 'agentssettings', 'evalssettings'] as const
export const isPackSection = (section: string): section is typeof packSections[number] => packSections.some(name => name === section)

const connectSections = ['payments', 'storage', 'integrations', 'forms', 'notifications', 'notiftypes', 'webhooks', 'providers', 'apiedge', 'import', 'apikeys', 'apps', ...packSections] as const
export const isConnectSection = (section: string): section is typeof connectSections[number] =>
  connectSections.some(name => name === section)

export const operateSections = ['observability', 'jobs', 'workers', 'workflows', 'traces', 'metrics', 'search'] as const
export const isOperateSection = (section: string): section is typeof operateSections[number] =>
  operateSections.some(name => name === section)

export const desktopSections = ['code', 'model', 'machines', 'permissions', 'access', 'specdiff', 'hooks', 'hookeffects', 'diagram-editor', 'api-client', 'import-mapping', 'template-editor'] as const

export type ProjectSection = typeof guidedSections[number] | typeof advancedGroups[number]['sections'][number] | typeof desktopSections[number]
export const projectSections = new Set<string>([...guidedSections, ...advancedGroups.flatMap(group => [...group.sections]), ...desktopSections])
export const isProjectSection = (section: string): section is ProjectSection => projectSections.has(section)
export const isGuidedSection = (section: string) => guidedSections.some(id => id === section)
export const isDesktopSection = (section: string) => desktopSections.some(id => id === section)

export function statusSection(id: string): ProjectSection {
  if (id === 'authorization') return 'access'
  if (id === 'state_machines') return 'machines'
  return isProjectSection(id) ? id : 'model'
}

export function projectPath(projectId: string, section: ProjectSection = 'overview') {
  return `/projects/${encodeURIComponent(projectId)}/${section}`
}

export type SectionSearch = {
  tab?: string
  kind?: string
  risk?: string
  decision?: string
  owner?: string
  history?: number
  preview?: string
  hook?: string
  entity?: string
  file?: string
  openFiles?: string[]
  source?: 'manifest' | 'kit'
  q?: string
  line?: number
  tool?: string
  workbench?: 'console' | 'reference'
  view?: string
  audience?: string
  diagramPick?: string
  diagramPages?: Record<string, number>
  base?: number
  role?: string
  run?: string
  rule?: string
  span?: string
  report?: string
  edit?: string
  phase?: number
  workspace?: string
  page?: number
  approval?: string
  tokensPage?: number
  notificationType?: string
  bookingKind?: number
  notificationRow?: number
  channel?: string
  subscription?: string
  delivery?: string
  limit?: string
  batch?: string
  recordPage?: number
  auditPage?: number
}

export function defaultSectionSearch(section: string): SectionSearch {
  if (section === 'deployment') return { tab: 'guided' }
  if (section === 'payments' || section === 'storage' || section === 'observability') return { tab: 'form' }
  return {}
}
