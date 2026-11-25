import type { ReactNode } from 'react'
import { useLanguage } from '../../../i18n'
import { Alert, Badge, Card, Row, Stack, Table } from '../../../ui'
import { gatewayOutputCost, gatewayPrices } from '../../../validators/advancedPacks'
import type { ConnectSpec } from '../api/connect'
import type { PackBlock } from '../api/packs'
import { advancedPackDefinitions, record, rows, strings } from '../state/advancedPacks'
import type { AdvancedPackScreen } from '../state/advancedPacks'
import { SectionLink } from './BlockStatus'
import type { ProjectRole } from './AdvancedPackFields'

type LinkedPack = { section: string; ready?: boolean }
type Props = {
  projectId: string; screen: AdvancedPackScreen; draft: PackBlock | null; roles?: ProjectRole[]; spec?: ConnectSpec
  prerequisites: LinkedPack[]; related: LinkedPack[]; version: number; row: number; updated: string | null
  gateway: PackBlock | null; agents: PackBlock | null; retentionConflict: boolean
}

function AccessByRole({ screen, draft, gateway, agents, roles, spec }: Pick<Props, 'screen' | 'gateway' | 'agents' | 'spec'> &
  { draft: PackBlock; roles: ProjectRole[] }) {
  const { t } = useLanguage()
  const local = screen === 'aigatewaysettings' || screen === 'agentssettings' ? record(draft.roles) : draft
  const roleFields = Object.keys(local).filter(field => field.endsWith('_roles'))
  if (!roleFields.length || !roles.length) return null
  const parents = new Map(spec?.auth?.roles.map(role => [role.name, role.inherits_from]))
  const effectiveRoles = (role: string) => {
    const result = new Set<string>()
    for (let current: string | null | undefined = role; current && !result.has(current); current = parents.get(current)) {
      result.add(current)
    }
    return result
  }
  const explicit = (role: Set<string>, value: unknown) => strings(value).some(name => role.has(name))
  const permitted = (role: Set<string>, ...values: unknown[]) => values.some(value =>
    strings(value).length === 0 || explicit(role, value))
  const agentReaders = (roles: Record<string, unknown>) => [
    roles.run_roles, roles.approve_roles, ...(strings(roles.read_roles).length ? [roles.read_roles] : []),
  ]
  const checks = (role: Set<string>, field: string) => {
    const allow = (...fields: string[]) => permitted(role, ...fields.map(key => local[key]))
    const gatewayRoles = record(gateway?.roles)
    const call = Boolean(gateway) && permitted(role, gatewayRoles.call_roles, gatewayRoles.manage_roles)
    switch (screen) {
      case 'aigatewaysettings':
        if (field === 'call_roles') return call
        if (field === 'read_roles') return allow(field, 'manage_roles')
        break
      case 'aidocssettings':
        if (field === 'upload_roles') return call && allow(field)
        if (field === 'read_roles') return allow(field, 'upload_roles', 'review_roles')
        break
      case 'knowledgesettings':
        if (field === 'read_roles') return allow(field, 'manage_roles')
        break
      case 'agentssettings':
        if (field === 'run_roles') return call && allow(field)
        if (field === 'read_roles') return permitted(role, ...agentReaders(local))
        break
      case 'evalssettings':
        return Boolean(agents) && call && permitted(role, local.run_roles, record(agents?.roles).approve_roles)
    }
    return allow(field)
  }
  const columns = roleFields.map(id => ({ id, label: t('connectD.field.' + id) }))
  if (screen === 'knowledgesettings') columns.push({ id: 'ask', label: t('connectD.ask') })
  if (screen === 'evalssettings') columns.push({ id: 'results', label: t('connectD.results') })
  return <Card><Stack><h2>{t('connectD.accessByRole')}</h2>
    <Table label={t('connectD.accessByRole')} columns={[{ id: 'role', label: t('connectD.role') }, ...columns]}
      rows={roles.map(({ name, label }) => ({
        id: name, cells: [t('schema.option', { value: label || name }), ...columns.map(({ id }) => {
          const effective = effectiveRoles(name)
          if (screen === 'aidocssettings' && id === 'read_roles') {
            const tenant = explicit(effective, local.read_roles) || explicit(effective, local.review_roles)
            return t(tenant ? 'connectD.tenant' : checks(effective, id) ? 'connectD.ownOnly' : 'connectD.restricted')
          }
          const allowed = id === 'ask' ? Boolean(gateway) && checks(effective, 'read_roles') &&
            permitted(effective, record(gateway?.roles).call_roles, record(gateway?.roles).manage_roles) :
            id === 'results' ? Boolean(agents) && permitted(effective, local.run_roles, ...agentReaders(record(agents?.roles))) : checks(effective, id)
          return t(allowed ? 'connectD.allowed' : 'connectD.restricted')
        })],
      }))} />
  </Stack></Card>
}

function PackDetails({ screen, draft, gateway }: { screen: AdvancedPackScreen; draft: PackBlock; gateway: PackBlock | null }) {
  const { t, language } = useLanguage()
  const number = new Intl.NumberFormat(language)
  const usd = new Intl.NumberFormat(language, { style: 'currency', currency: 'USD', maximumFractionDigits: 6 })
  const percentage = new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 2 })
  const values: [string, string][] = []
  if (screen === 'matchingsettings') {
    const weights = record(draft.weights)
    const total = Number(weights.distance) + Number(weights.load) + Number(weights.rating)
    if (total > 0 && Object.values(weights).every(weight => typeof weight === 'number' && weight >= 0)) for (const key of ['distance', 'load', 'rating']) {
      values.push([t('connectD.field.' + key), percentage.format(Number(weights[key]) / total)])
    }
  }
  if (screen === 'predictionsettings' && typeof draft.interval_bp === 'number') {
    const half = Math.max(1, Math.floor(draft.interval_bp / 10))
    values.push([t('connectD.intervalExample'), t('connectD.intervalBounds', {
      low: number.format(1000 - half), high: number.format(1000 + half), unit: String(draft.unit),
    })])
  }
  if (screen === 'aigatewaysettings' || screen === 'knowledgesettings') {
    const settings = screen === 'aigatewaysettings' ? draft : gateway
    const budget = record(settings?.budget)
    if (typeof budget.limit_micro_usd === 'number') values.push([t('connectD.field.limit_micro_usd'), usd.format(budget.limit_micro_usd / 1_000_000)])
    if (typeof budget.per_call_cap_micro_usd === 'number') values.push([t('connectD.field.per_call_cap_micro_usd'), usd.format(budget.per_call_cap_micro_usd / 1_000_000)])
    for (const stage of rows(settings?.stages)) {
      if (screen === 'knowledgesettings' && stage.name !== draft.stage) continue
      if (screen === 'knowledgesettings' && typeof stage.model === 'string') {
        values.push([t('connectD.field.model'), stage.model])
        const price = gatewayPrices[stage.model as keyof typeof gatewayPrices]
        if (price) {
          values.push([t('connectD.prices'), t('connectD.modelPrice', {
            input: usd.format(price[0] / 1_000_000), output: usd.format(price[1] / 1_000_000),
          })])
        }
      }
      const cost = gatewayOutputCost(stage.max_output_tokens, stage.model, stage.fallback_model)
      if (cost != null) values.push([t('connectD.outputCost', { stage: String(stage.name || stage.model) }), usd.format(cost / 1_000_000)])
    }
  }
  if (screen === 'aidocssettings') {
    if (typeof draft.review_below_bp === 'number') {
      values.push([t('connectD.field.review_below_bp'), percentage.format(draft.review_below_bp / 10_000)])
    }
    if (typeof draft.max_text_chars === 'number' && draft.max_text_chars > 0) {
      values.push([t('connectD.effectiveUploadLimit'), number.format(Math.min(draft.max_text_chars, 380_000))])
    }
    const stage = rows(gateway?.stages).find(stage => stage.name === draft.stage)
    if (typeof stage?.model === 'string') values.push([t('connectD.field.model'), stage.model])
  }
  const prices = screen === 'aigatewaysettings' && <Table label={t('connectD.prices')} columns={[
    { id: 'model', label: t('connectD.field.model') }, { id: 'input', label: t('connectD.inputPrice') },
    { id: 'output', label: t('connectD.outputPrice') },
  ]} rows={Object.entries(gatewayPrices).map(([model, [input, output]]) => ({
    id: model, cells: [t('schema.option', { value: model }), usd.format(input / 1_000_000), usd.format(output / 1_000_000)],
  }))} />
  return <Card><Stack>
    <h2>{t('connectD.screen.' + screen + '.reference')}</h2>
    <p>{t('connectD.screen.' + screen + '.guide')}</p>
    {values.length > 0 && <Table label={t('connectD.calculated')} columns={[
      { id: 'setting', label: t('connectD.setting') }, { id: 'value', label: t('connectD.value') },
    ]} rows={values.map(([key, value], index) => ({ id: String(index), cells: [key, value] }))} />}
    {prices}
  </Stack></Card>
}

export function AdvancedPackReference(props: Props) {
  const { projectId, screen, draft, spec, prerequisites, related, roles, version, row, updated, retentionConflict } = props
  const { t, language } = useLanguage()
  const definition = advancedPackDefinitions[screen]
  const date = updated && !Number.isNaN(Date.parse(updated)) ? new Intl.DateTimeFormat(language, {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date(updated)) : null
  const authReady = spec ? Boolean(spec.auth?.enabled) && (definition.address[0] !== 'ai' || spec.auth?.provider !== 'keycloak') : undefined
  const requirements = [{ section: 'auth', ready: authReady },
    { section: 'access', ready: spec ? !spec.authorization || spec.authorization.model === 'rbac' : undefined }, ...prerequisites]
  const linkRows = (items: LinkedPack[], required = false) => <Stack gap={2}>{items.map(({ section, ready }) =>
    <Row key={section}>
      <SectionLink projectId={projectId} section={section} label={t('nav.' + section)} />
      {ready !== undefined && <Badge tone={ready ? 'success' : 'neutral'}>
        {t(ready ? 'connectD.ready' : required ? 'connectD.required' : 'connectD.off')}
      </Badge>}
    </Row>)}</Stack>
  const gatedAgents = screen === 'evalssettings' ? rows(props.agents?.agents).filter(agent => agent.require_eval != null) : []
  return <aside aria-label={t('connectD.reference')}><Stack>
    <Card><Stack><h2>{t('connectD.dependencies')}</h2>
      {linkRows(requirements, true)}
      {definition.address[0] === 'ai' && <p>{t('connectD.builtinAuth')}</p>}
      {retentionConflict && <Alert tone="warning">{t('connectD.retentionConflict')}</Alert>}
    </Stack></Card>
    {draft && <PackDetails screen={screen} draft={draft} gateway={props.gateway} />}
    {draft && roles && <AccessByRole {...props} draft={draft} roles={roles} />}
    {gatedAgents.length > 0 && <Card><Stack><h2>{t('connectD.evalGates')}</h2>
      {gatedAgents.map(agent => <p key={String(agent.name)}>{t('connectD.evalGate', { agent: String(agent.name), suite: String(agent.require_eval) })}</p>)}
    </Stack></Card>}
    <Card><Stack><h2>{t('connectD.generated')}</h2>
      <p>{t('connectD.generatedHelp')}</p>
      <code>{t('schema.option', { value: definition.route })}</code>
      {definition.tables.map(table => <code key={table}>{t('schema.option', { value: table })}</code>)}
      {related.length > 0 && linkRows(related)}
    </Stack></Card>
    <Card><Stack><h2>{t('connectD.savedSettings')}</h2>
      <dl>{[
        [t('connectD.version'), t('connectD.metadata', { value: version })],
        [t('connectD.row'), t('connectD.metadata', { value: row })],
        [t('connectD.updated'), date ?? t('connectD.never')],
      ].map(([label, value]): ReactNode => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </Stack></Card>
  </Stack></aside>
}
