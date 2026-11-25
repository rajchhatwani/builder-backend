import type { ProjectSection } from '../../projectNavigation'

export const audiences = ['ALL', 'BIZ', 'PM', 'ARCH', 'DEV', 'SEC', 'OPS'] as const
type Audience = typeof audiences[number]

export const catalogue = [
  { id: 'D01', audiences: 'BIZ PM ARCH SEC', support: 'P', source: 'overview' },
  { id: 'D02', audiences: 'PM ARCH DEV OPS', support: 'P', source: 'generate' },
  { id: 'D03', audiences: 'ARCH DEV', support: 'Y', source: 'generate' },
  { id: 'D04', audiences: 'BIZ PM', support: 'Y', source: 'overview' },
  { id: 'D05', audiences: 'BIZ PM ARCH DEV SEC', support: 'Y', source: 'model' },
  { id: 'D06', audiences: 'ARCH DEV', support: 'P', source: 'model' },
  { id: 'D07', audiences: 'BIZ PM ARCH DEV', support: 'Y', source: 'machines' },
  { id: 'D08', audiences: 'BIZ PM ARCH DEV SEC', support: 'P', source: 'payments' },
  { id: 'D09', audiences: 'ARCH DEV SEC', support: 'Y', source: 'hooks' },
  { id: 'D10', audiences: 'DEV SEC', support: 'Y', source: 'model' },
  { id: 'D11', audiences: 'ARCH DEV SEC', support: 'P', source: 'auth' },
  { id: 'D12', audiences: 'BIZ PM ARCH DEV SEC', support: 'Y', source: 'permissions' },
  { id: 'D13', audiences: 'PM DEV SEC', support: 'Y', source: 'permissions' },
  { id: 'D14', audiences: 'ARCH DEV SEC', support: 'Y', source: 'access' },
  { id: 'D15', audiences: 'PM ARCH DEV SEC', support: 'P', source: 'auth' },
  { id: 'D16', audiences: 'ARCH SEC', support: 'Y', source: 'suite' },
  { id: 'D17', audiences: 'ARCH SEC', support: 'P', source: 'auth' },
  { id: 'D18', audiences: 'ARCH DEV SEC', support: 'P', source: 'model' },
  { id: 'D19', audiences: 'PM ARCH DEV OPS', support: 'P', source: 'events' },
  { id: 'D20', audiences: 'ARCH DEV', support: 'Y', source: 'overview' },
  { id: 'D21', audiences: 'ARCH DEV OPS', support: 'Y', source: 'jobs' },
  { id: 'D22', audiences: 'DEV OPS', support: 'Y', source: 'jobs' },
  { id: 'D23', audiences: 'BIZ PM ARCH DEV', support: 'Y', source: 'workflows' },
  { id: 'D24', audiences: 'BIZ PM', support: 'P', source: 'workflows' },
  { id: 'D25', audiences: 'BIZ PM', support: 'P', source: 'intake' },
  { id: 'D26', audiences: 'BIZ PM', support: 'N', source: undefined },
  { id: 'D27', audiences: 'BIZ PM ARCH DEV SEC OPS', support: 'Y', source: 'integrations' },
  { id: 'D28', audiences: 'BIZ PM ARCH DEV SEC OPS', support: 'Y', source: 'payments' },
  { id: 'D29', audiences: 'ARCH DEV SEC', support: 'Y', source: 'storage' },
  { id: 'D30', audiences: 'BIZ PM ARCH DEV SEC', support: 'Y', source: 'aigatewaysettings' },
  { id: 'D31', audiences: 'ARCH DEV', support: 'Y', source: 'model' },
  { id: 'D32', audiences: 'ARCH OPS', support: 'P', source: 'deployment' },
  { id: 'D33', audiences: 'DEV OPS', support: 'Y', source: 'generate' },
  { id: 'D34', audiences: 'ARCH DEV SEC OPS', support: 'Y', source: 'deployment' },
  { id: 'D35', audiences: 'ARCH OPS', support: 'Y', source: 'observability' },
  { id: 'D36', audiences: 'DEV OPS', support: 'P', source: 'traces' },
  { id: 'D37', audiences: 'ARCH DEV SEC OPS', support: 'Y', source: 'apiedge' },
  { id: 'D38', audiences: 'BIZ SEC', support: 'Y', source: 'compliance' },
  { id: 'D39', audiences: 'ARCH SEC', support: 'P', source: 'compliance' },
  { id: 'D40', audiences: 'BIZ SEC', support: 'Y', source: 'history' },
  { id: 'D41', audiences: 'BIZ PM ARCH DEV SEC', support: 'Y', source: 'timeline' },
  { id: 'D42', audiences: 'PM ARCH DEV', support: 'Y', source: 'generate' },
  { id: 'D43', audiences: 'BIZ PM', support: 'P', source: 'intake' },
  { id: 'D44', audiences: 'BIZ PM', support: 'Y', source: 'metrics' },
  { id: 'D45', audiences: 'BIZ PM OPS', support: 'Y', source: 'map' },
  { id: 'D46', audiences: 'BIZ PM DEV', support: 'Y', source: 'bookingsettings' },
  { id: 'D47', audiences: 'BIZ PM DEV SEC', support: 'P', source: 'ledger' },
] as const satisfies readonly { id: string; audiences: string; support: 'Y' | 'P' | 'N'; source?: ProjectSection }[]

export type DiagramId = typeof catalogue[number]['id']
export const topics: Record<string, readonly DiagramId[]> = {
  architecture: ['D01', 'D02', 'D03', 'D04', 'D31'],
  data: ['D05', 'D06', 'D40', 'D44'],
  behaviour: ['D07', 'D08', 'D09', 'D10', 'D11', 'D20', 'D37'],
  security: ['D12', 'D13', 'D14', 'D15', 'D16', 'D17', 'D38', 'D39'],
  integrations: ['D18', 'D19', 'D21', 'D22', 'D23', 'D27', 'D28', 'D29', 'D30', 'D45', 'D46', 'D47'],
  delivery: ['D32', 'D33', 'D34', 'D35', 'D36', 'D42'],
  businessandchange: ['D24', 'D25', 'D26', 'D41', 'D43'],
}

export function filterCatalogue(audience: string | undefined) {
  const current = audiences.find(value => value === audience) ?? 'ALL'
  return { current, diagrams: catalogue.filter(diagram => current === 'ALL' || diagram.audiences.split(' ').includes(current satisfies Audience)) }
}
