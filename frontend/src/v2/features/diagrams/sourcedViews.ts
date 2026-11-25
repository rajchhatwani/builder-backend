import type { DiagramSources } from './api/diagrams'
import { architectureViews } from './architectureViews'
import { dataViews, relationship } from './dataViews'
import { integrationViews } from './integrationViews'
import { securityViews } from './securityViews'
import type { DiagramId } from './catalogue'
import type { Diagram, Spec, Translate } from './model'
import { choose, graph, hub, objects, str, table } from './model'

function manifest(paths: string[], w: Translate, selection?: string): Diagram {
  const groups = new Map<string, string[]>()
  for (const path of paths) {
    const parts = path.split('/')
    if (parts[0] !== 'app' || parts.length < 2) continue
    const key = parts.length > 2 ? parts[1] : w('appRoot')
    groups.set(key, [...groups.get(key) ?? [], path])
  }
  const components = [...groups].sort(([a], [b]) => a.localeCompare(b))
  const picker = choose(w('component'), components.map(([value]) => ({ value, label: value })), selection)
  return groups.size ? {
    ...hub({ name: w('generatedApi') }, components.map(([name, paths]) => ({ name, detail: w('fileCount', { count: paths.length }) }))),
    picker, files: groups.get(picker.value),
  } : {}
}

function matrix(spec: Spec, data: DiagramSources, w: Translate, selection: string | undefined): Diagram {
  const matrix = data.matrix
  if (!matrix?.entities.length) return {}
  const picker = choose(w('entityAndLayer'), matrix.entities.flatMap(entity =>
    ['object', 'row', 'field'].map(layer => ({ value: entity + ':' + layer, label: w('entityLayer', { entity, layer: w(layer + 'Layer') }) }))), selection)
  const [entity, layer] = picker.value.split(':')
  const cells = matrix.cells.filter(cell => cell.entity === entity && cell.layer === layer)
  const indexed = new Map(cells.map(cell => [JSON.stringify([cell.target, cell.role]), cell.value]))
  const targets = [...new Set(cells.map(cell => cell.target))]
  const config = spec.authorization
  return {
    picker,
    tables: [table([w('target'), ...matrix.roles.map(role => role === '(public)' ? w('public') : role)],
      targets.map(target => [target, ...matrix.roles.map(role => indexed.get(JSON.stringify([target, role])))]))],
    note: config ? w('matrixLayers') : undefined,
  }
}

function history(spec: Spec, data: DiagramSources, w: Translate): Diagram {
  const ops = data.ops ?? []
  if (!data.before || !ops.length) return {}
  const choices = ops.map(op => ({ value: String(op.seq), label: w('versionChoice', { count: op.seq, action: op.op_type }) }))
  if (data.version && !ops.some(op => op.seq === data.version)) {
    choices.unshift({ value: String(data.version), label: w('versionNumber', { count: data.version }) })
  }
  const picker = choose(w('compareWith'), [...choices, { value: '0', label: w('beforeFirst') }], String(data.version))
  const before = data.before
  const changes = (previous: unknown, current: unknown, key: (row: Spec) => string) => {
    const old = new Map(objects(previous).map(row => [key(row), row]))
    const now = new Map(objects(current).map(row => [key(row), row]))
    return [...new Set([...old.keys(), ...now.keys()])].map(name => {
      const was = old.get(name)
      const is = now.get(name)
      return { row: is ?? was!, change: w(!was ? 'added' : !is ? 'removed' : JSON.stringify(was) === JSON.stringify(is) ? 'unchanged' : 'changed') }
    })
  }
  const entities = changes(before.entities, spec.entities, row => str(row.name))
  const relations = changes(before.relations, spec.relations, row => JSON.stringify([row.from_entity, row.to_entity, row.from_name]))
  const names = entities.map(item => str(item.row.name))
  return {
    ...graph(entities.map(({ row, change }) => ({ name: str(row.name), detail: change })), relations.flatMap(({ row, change }): [number, number, string][] => {
      const from = names.indexOf(str(row.from_entity))
      const to = names.indexOf(str(row.to_entity))
      return from < 0 || to < 0 ? [] : [[from, to, [str(row.from_name), change].join(' · ')]]
    })),
    picker,
    tables: [
      table(['entity', 'change'].map(key => w(key)), entities.map(({ row, change }) => [str(row.name), change])),
      table(['from', 'relation', 'to', 'change'].map(key => w(key)), relations.map(({ row, change }) =>
        [str(row.from_entity), str(row.from_name), str(row.to_entity), change])),
      table(['version', 'change', 'actor'].map(key => w(key)), ops.map(op => [op.seq, op.op_type, op.actor.email ?? op.actor.kind]), w('recentChanges')),
    ],
  }
}

function requirements(data: DiagramSources, w: Translate, selection?: string): Diagram {
  const phases = data.requirements?.phases ?? []
  const rows = data.requirements?.items ?? []
  if (!rows.length) return {}
  const picker = choose(w('phase'), [{ value: 'all', label: w('allPhases') }, ...phases.map(phase => ({
    value: String(phase.number), label: phase.name,
  }))], selection)
  const scoped = phases.find(phase => String(phase.number) === picker.value)
  return {
    picker,
    tables: [table(['kind', 'requirement', 'status', 'coveredBy'].map(key => w(key)),
      rows.filter(item => !scoped || scoped.kinds.includes(item.kind)).map(item => [item.kind, item.text, w(item.status), item.covered_by]))],
  }
}

const builders = { ...dataViews, ...architectureViews, ...integrationViews, ...securityViews }
export function buildDiagram(id: DiagramId, spec: Spec, data: DiagramSources, w: Translate, selection?: string, audience?: string): Diagram {
  switch (id) {
    case 'D03': return { ...manifest(data.paths ?? [], w, selection), note: w(data.paths ? 'generationSource' : 'noGeneration') }
    case 'D05': return relationship(spec, w, selection, audience === 'BIZ')
    case 'D13': return matrix(spec, data, w, selection)
    case 'D36': return {}
    case 'D41': return history(spec, data, w)
    case 'D42': {
      const diagram = builders.D42(spec, w)
      return { ...diagram, tables: [...diagram.tables, table([w('generation'), w('files'), w('size')],
        (data.generations ?? []).map(item => [new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(item.created_at)), item.file_count, item.total_size]), w('recentGenerations'))] }
    }
    case 'D43': return requirements(data, w, selection)
    default: return builders[id](spec, w, selection)
  }
}
