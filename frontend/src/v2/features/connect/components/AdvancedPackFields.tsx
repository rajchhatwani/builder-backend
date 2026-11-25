import type { Path } from '../../../../forms/schemaLogic'
import type { JsonSchema, PathErrors } from '../../../../forms/types'
import { useLanguage, useT } from '../../../i18n'
import { SchemaFields } from '../../../patterns/SchemaFields'
import type { SchemaFieldOverride } from '../../../patterns/SchemaFields'
import { Alert, Card, Checkbox, Stack } from '../../../ui'
import { gatewayPrices } from '../../../validators/advancedPacks'
import type { ConnectSpec } from '../api/connect'
import type { PackBlock } from '../api/packs'
import { names, packGroups, record, rows, strings } from '../state/advancedPacks'
import type { AdvancedPackScreen } from '../state/advancedPacks'

export type ProjectRole = { name: string; label: string }
const autonomy = ['suggest', 'draft', 'auto']

export function packChoices({ screen, draft, spec, roles, gateway, agents, evals }: {
  screen: AdvancedPackScreen; draft: PackBlock; spec?: ConnectSpec; roles?: ProjectRole[]
  gateway: PackBlock | null; agents: PackBlock | null; evals: PackBlock | null
}) {
  return (path: Path): string[] | undefined => {
    const field = String(path.at(-1))
    if (field.endsWith('_roles')) return roles?.map(role => role.name)
    if (screen === 'aigatewaysettings') {
      if (field === 'kind') return ['fake']
      if (field === 'provider') return names(draft.providers)
      if (field === 'model' || field === 'fallback_model') return Object.keys(gatewayPrices)
      if (field === 'period') return ['day', 'month']
    }
    if (field === 'stage') {
      const stages = names(gateway?.stages)
      return stages.length ? stages : undefined
    }
    if (screen === 'agentssettings') {
      const entry = rows(draft[path[0]])[Number(path[1])]
      if (field === 'kind') return ['note', 'entity_create']
      if (field === 'risk') return ['low', 'medium', 'high']
      if (field === 'autonomy' || field === 'max_autonomy') return autonomy
      if (field === 'actions' && path[0] === 'agents') return names(draft.actions)
      if (field === 'entity') return spec?.entities.flatMap(entity => entity.table_name ? [entity.table_name] : [])
      if (field === 'fields') {
        const entity = spec?.entities.find(entity => entity.table_name === entry?.entity)
        if (!spec || !entity) return
        const createRoles = spec.auth?.permissions?.filter(permission =>
          permission.entity === entity.name && permission.operation === 'create').flatMap(permission => permission.roles) ?? []
        const protectedFields = new Set([
          ...(spec.state_machines ?? []).filter(machine => machine.entity === entity.name).map(machine => machine.field),
          ...(spec.sequences ?? []).filter(sequence => sequence.entity === entity.name).map(sequence => sequence.field),
          ...(spec.authorization?.field_access ?? []).filter(access => access.entity === entity.name && access.write_roles != null &&
            createRoles.some(role => !access.write_roles!.includes(role))).map(access => access.field),
        ])
        return entity.fields.filter(field => field.type !== 'file' && !protectedFields.has(field.name)).map(field => field.name)
      }
      if (field === 'require_eval') return names(rows(evals?.suites).filter(suite => suite.agent === entry?.name))
    }
    if (screen === 'evalssettings') {
      if (field === 'agent') return names(agents?.agents)
      if (field === 'forbid_actions') return names(agents?.actions)
      if (field === 'expect_actions') {
        const suite = rows(draft.suites)[Number(path[1])]
        return strings(rows(agents?.agents).find(agent => agent.name === suite?.agent)?.actions)
      }
    }
  }
}

export function packFieldName(path: Path) {
  return path[0] === 'actions' && path.at(-1) === 'fields' ? 'allowed_fields' : String(path.at(-1))
}

function PackMultiChoice({ value, onChange, readOnly, error, id, options, label, help, onBlur }: SchemaFieldOverride & {
  options: Map<string, string>; label: string; help?: string; onBlur: () => void
}) {
  const t = useT()
  const selected = strings(value)
  const entries = Array.from(new Set([...options.keys(), ...selected]))
  return <fieldset className="v2-pack-fieldset" aria-describedby={id + '-description'} tabIndex={error ? -1 : undefined}
    aria-invalid={error ? true : undefined}>
    <legend>{label}</legend>
    <Stack gap={1}>
      <Stack gap={1}>
        {entries.map(name => <Checkbox key={name} label={options.has(name) ?
          t('schema.option', { value: options.get(name)! }) : t('connectD.unavailableOption', { name })}
          checked={selected.includes(name)} disabled={readOnly} onBlur={onBlur}
          onChange={event => onChange(event.target.checked ? [...selected, name] : selected.filter(item => item !== name))} />)}
      </Stack>
      <div id={id + '-description'} className="v2-muted">
        {help && <p>{help}</p>}
        {!entries.length && <p>{t('connectD.noOptions')}</p>}
        {error && <Alert tone="danger">{t('common.serverText', { text: error })}</Alert>}
      </div>
    </Stack>
  </fieldset>
}

export function AdvancedPackFields({ screen, schema, draft, roles, choices, errors, readOnly, revision, onChange, onBlur,
  onStructure, removeImpact }: {
  screen: AdvancedPackScreen; schema: JsonSchema; draft: PackBlock; roles?: ProjectRole[]
  choices: (path: Path) => string[] | undefined; errors: PathErrors; readOnly: boolean; revision: number
  onChange: (path: Path, value: unknown) => void; onBlur: (path: string) => void; onStructure: (path: string) => void
  removeImpact: (path: Path, value: unknown) => string | undefined
}) {
  const { t, language } = useLanguage()
  const fieldOverride = (control: SchemaFieldOverride) => {
    const { path } = control
    const field = String(path.at(-1))
    const label = t('connectD.field.' + packFieldName(path))
    const available = choices(path)
    if (!available || !Array.isArray(control.value)) return
    const options = new Map(available.map(name => [name, roles?.find(role => field.endsWith('_roles') && role.name === name)?.label || name]))
    const help = field === 'read_roles' && ['agentssettings', 'aidocssettings', 'knowledgesettings'].includes(screen)
      ? t('connectD.help.' + screen + 'Read')
      : field.endsWith('_roles') || ['expect_actions', 'forbid_actions'].includes(field) || packFieldName(path) === 'allowed_fields'
        ? t('connectD.help.' + packFieldName(path)) : undefined
    const error = [control.error, ...Object.entries(errors).filter(([key]) => key.startsWith(path.join('.') + '.'))
      .flatMap(([, messages]) => messages)].filter(Boolean).join(' ')
    return <PackMultiChoice {...control} error={error} options={options} label={label} help={help} onBlur={() => onBlur(path.join('.'))} />
  }
  const rowDetail = (path: Path, value: unknown) => {
    const row = record(value)
    if (path[0] === 'suites' && path.length === 1 && typeof row.pass_bp === 'number') {
      const passMark = new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 2 }).format(row.pass_bp / 10_000)
      return <p className="v2-muted">{t('connectD.passMark', { passMark })}</p>
    }
  }
  return <Stack>{packGroups(screen, schema).map(({ group, fields, schema }) => {
    const fieldsView = <SchemaFields key={revision} schema={schema} value={draft} onChange={(path, value) => {
      if (screen === 'agentssettings' && path[0] === 'actions' && path.at(-1) === 'kind' && value === 'note') {
        const parent = path.slice(0, -1)
        onChange(parent, { ...rows(draft.actions)[Number(path[1])], kind: value, entity: null, fields: [] })
        return
      }
      onChange(path, value)
    }} errors={errors} readOnly={readOnly} onBlur={onBlur} onStructure={onStructure} fieldOverride={fieldOverride}
      confirmRemove groupHeadings showEmptyRows rowDetail={rowDetail} removeImpact={removeImpact}
      options={path => {
        const options = choices(path)
        return options?.map(value => ({ value, label: t('schema.option', { value }) }))
      }} />
    const node = fields.length === 1 ? schema.properties?.[fields[0]] : undefined
    if (node?.type === 'object' || node?.type === 'array') return <div key={group}>{fieldsView}</div>
    return <Card key={group}><Stack><h2>{t('connectD.group.' + group)}</h2>{fieldsView}</Stack></Card>
  })}</Stack>
}
