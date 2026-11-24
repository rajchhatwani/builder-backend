/** URL contract shared by the application router and project screens. */
export const guidedSections = ['intake', 'plan', 'build', 'approvals', 'see'] as const
export const advancedGroups = [
  { id: 'home', sections: ['overview', 'code'] },
  { id: 'build', sections: ['model', 'machines', 'settings', 'history', 'hooks', 'seed', 'specdiff'] },
  { id: 'secure', sections: ['auth', 'keycloak', 'access'] },
  { id: 'connect', sections: ['payments', 'storage', 'documents', 'import'] },
  { id: 'operate', sections: ['observability', 'logs', 'metrics'] },
  { id: 'ship', sections: ['generate', 'deployment', 'upgrades'] },
  { id: 'diagrams', sections: ['diagrams'] },
] as const

export const desktopSections = ['code', 'model', 'machines', 'access', 'specdiff', 'hooks', 'hookeffects', 'diagram-editor', 'api-client', 'import-mapping', 'template-editor'] as const

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
  entity?: string
  file?: string
  tool?: string
  view?: string
  role?: string
  run?: string
  phase?: number
  workspace?: string
  page?: number
  approval?: string
}
