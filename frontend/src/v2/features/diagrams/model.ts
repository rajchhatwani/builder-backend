export type Spec = Record<string, unknown>
export type Translate = (key: string, values?: Record<string, string | number>) => string
export type Cell = string | number | boolean | undefined | null
export type Node = { name: string; detail?: string; members?: string[] }
export type Edge = { from: number; to: number; label?: string }
export type DiagramTable = { heading?: string; columns: string[]; rows: Cell[][] }
export type Picker = { label: string; value: string; options: { value: string; label: string }[] }
export type Diagram = {
  nodes?: Node[]
  edges?: Edge[]
  tables?: DiagramTable[]
  picker?: Picker
  note?: string
  files?: string[]
}
export type Builder = (spec: Spec, w: Translate, selection?: string) => Diagram

export function record(value: unknown): Spec {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Spec : {}
}

export function objects(value: unknown): Spec[] {
  return Array.isArray(value)
    ? value.filter(entry => entry && typeof entry === 'object' && !Array.isArray(entry)).map(record)
    : []
}

export function words(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []
}

export function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function cell(value: unknown): Cell {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  return words(value).join(', ') || undefined
}

export function active(value: unknown) {
  return Boolean(value && typeof value === 'object' && record(value).enabled !== false)
}

export function nodes(rows: Pick<Node, 'name' | 'detail'>[]): Node[] {
  return rows.filter(row => row.name)
}

export function graph(rows: Node[], links: [number, number, string?][] = []): Diagram {
  return { nodes: rows, edges: links.map(([from, to, label]) => ({ from, to, label })) }
}

export function chain(rows: Node[]): Diagram {
  return graph(rows, rows.slice(1).map((_, i) => [i, i + 1]))
}

export function hub(root: Node, leaves: Node[]): Diagram {
  return graph([root, ...leaves], leaves.map((_, i) => [0, i + 1]))
}

export function table(columns: string[], rows: Cell[][], heading?: string): DiagramTable {
  return { columns, rows, heading }
}

export function columns(w: Translate, labels: string[], rows: Spec[], keys: string[], heading?: string) {
  return table(labels.map(label => w(label)), rows.map(row => keys.map(key => cell(row[key]))), heading)
}

export function named(rows: Spec[], field?: string): Node[] {
  return nodes(rows.map(row => ({ name: str(row.name), detail: field ? str(row[field]) : undefined })))
}

export function choose(label: string, options: Picker['options'], selection: string | undefined) {
  const entries = [...new Map(options.filter(option => option.value).map(option => [option.value, option])).values()]
  return { label, options: entries, value: entries.some(option => option.value === selection) ? selection! : entries[0]?.value ?? '' }
}

export function chooseRows(label: string, rows: Spec[], selection: string | undefined, key = 'name') {
  const picker = choose(label, rows.map(row => ({ value: str(row[key]), label: str(row.label) || str(row[key]) })), selection)
  return { picker, selected: rows.find(row => row[key] === picker.value) }
}

const lists = ['entities', 'relations', 'state_machines', 'settings', 'sequences', 'lists', 'history', 'hooks', 'seed', 'features']
const blocks = ['auth', 'payments', 'storage', 'authorization', 'observability', 'deployment', 'documents', 'events', 'providers',
  'notifications', 'jobs', 'workflows', 'api_edge', 'webhooks', 'hook_effects', 'realtime', 'metrics_layer', 'packs',
  'regulated', 'compliance', 'api_platform']

export function hasDiagramData(spec: Spec) {
  return lists.some(key => Array.isArray(spec[key]) && (spec[key] as unknown[]).length > 0)
    || blocks.some(key => active(spec[key]) && Object.keys(record(spec[key])).length > 0)
}

export function capabilities(spec: Spec, w: Translate): Node[] {
  const count = (key: string) => Array.isArray(spec[key]) ? (spec[key] as unknown[]).length : 0
  return [
    ...lists.filter(key => count(key)).map(key => ({ name: w(key), detail: w('count', { count: count(key) }) })),
    ...blocks.filter(key => active(spec[key])).map(key => ({ name: w(key) })),
  ]
}
