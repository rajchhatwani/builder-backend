import { useMutation, useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { Form, SettingsSection } from '../../patterns'
import { Badge, Button, Dialog, EmptyState, Grid, Pagination, Row, Stack, Table } from '../../ui'
import { accessChecks } from '../../validators'
import type { AccessEditorProps } from './AccessModel'
import { controlsApi, coverageOptions, type CoverageRow, type SimulateRequest } from './api/controls'
import { operations } from './state/access'
import { checkField, LoadFailure, numberField, pickField, readOptionalNumber, readText, SecureLink, SecureLoading, textField, useSecureSearch } from './SecureForm'

const choices = (values: string[]) => values.map(value => ({ value, label: value }))
const object = (value: string): Record<string, unknown> => value ? JSON.parse(value) as Record<string, unknown> : {}

export function AccessSimulator({ id, roles, spec }: AccessEditorProps) {
  const t = useT()
  const { search, filter } = useSecureSearch()
  const entity = spec.entities.find(item => item.name === search.entity) ?? spec.entities[0]
  const allowed = entity?.options?.operations ?? [...operations]
  const simulate = useMutation({ mutationFn: (value: SimulateRequest) => controlsApi.simulateAuthorization(id, value) })
  if (!entity) return <EmptyState title={t('authorization.noEntities')} action={<SecureLink id={id} section="model" label={t('authorization.dataModel')} />} />
  const fields = [
    pickField('entity', t('authorization.entity'), entity.name, choices(spec.entities.map(item => item.name)), {
      change: value => { simulate.reset(); filter({ entity: value }) },
    }),
    pickField('op', t('authorization.operation'), allowed[0] ?? '', allowed.map(value => ({
      value, label: t(`authorization.op_${value}`),
    })), { required: true }),
    textField('person', t('authorization.personId'), '', { max: 120 }),
    textField('email', t('authorization.email'), '', { max: 254, type: 'email' }),
    ...spec.auth?.multi_tenant ? [textField('tenant', t('authorization.tenantId'), '', { max: 120 })] : [],
    textField('attributes', t('authorization.subjectAttributes'), '', { area: true, checks: [accessChecks.jsonObject], hint: t('authorization.jsonHint') }),
    textField('record', t('authorization.record'), '', { area: true, checks: [accessChecks.jsonObject], hint: t('authorization.jsonHint') }),
    numberField('hour', t('authorization.hour'), null, { min: 0, max: 23, integer: true }, false),
    numberField('weekday', t('authorization.weekday'), null, { min: 0, max: 6, integer: true }, false),
    textField('ip', t('authorization.ip'), '', { max: 45 }),
    ...roles.map(role => checkField(`role.${role.name}`, role.label, false)),
  ]
  function run(data: FormData) {
    const attributes = object(readText(data, 'attributes'))
    const record = readText(data, 'record')
    const tenant = readText(data, 'tenant')
    const hour = readOptionalNumber(data, 'hour')
    const weekday = readOptionalNumber(data, 'weekday')
    const ip = readText(data, 'ip')
    simulate.mutate({
      entity: entity.name, op: readText(data, 'op'),
      subject: { ...attributes, id: readText(data, 'person'), email: readText(data, 'email'),
        roles: roles.filter(role => data.has(`role.${role.name}`)).map(role => role.name),
        ...(spec.auth?.multi_tenant && tenant ? { tenant_id: tenant } : {}) },
      resource: record ? object(record) : null,
      env: { ...(hour !== null ? { hour_utc: hour } : {}), ...(weekday !== null ? { weekday_utc: weekday } : {}),
        ...(ip ? { client_ip: ip } : {}) },
    })
  }
  const result = simulate.data
  return <SettingsSection title={t('authorization.tab_simulator')} description={t('authorization.simulatorHelp')}>
    <Form key={entity.name} fields={fields} pending={simulate.isPending} submitLabel={t('authorization.simulate')}
      layout={controls => <Stack>
        <Grid>{fields.filter(field => !field.name.startsWith('role.')).map(field => controls[field.name])}</Grid>
        {roles.length > 0 && <fieldset><legend>{t('authorization.tab_roles')}</legend><Grid>
          {fields.filter(field => field.name.startsWith('role.')).map(field => controls[field.name])}</Grid></fieldset>}
      </Stack>} onSubmit={run} />
    {simulate.isError && <LoadFailure error={simulate.error} message={t('authorization.simulationError')}
      retry={() => { if (simulate.variables) simulate.mutate(simulate.variables) }} />}
    {result && <Stack gap={2} role="status">
      <Row><Badge tone={result.allowed ? 'success' : 'danger'}>{t(result.allowed ? 'authorization.allowed' : 'authorization.denied')}</Badge><p>{result.reason}</p></Row>
      <p>{t('authorization.allowMatched', { policies: result.allow_matched.join(', ') || t('authorization.none') })}</p>
      <p>{t('authorization.denyMatched', { policies: result.deny_matched.join(', ') || t('authorization.none') })}</p>
      <ul>{result.trace.map((item, i) => <li key={i}><details><summary>{t('authorization.simulationTrace', {
        policy: item.policy, effect: t(`authorization.effect_${item.effect}`), result: t(item.condition_met ? 'authorization.yes' : 'authorization.no'),
      })}</summary><p>{item.condition}</p><ul>{item.leaves.map((leaf, index) => <li key={index}>{t('authorization.traceLeaf', {
        condition: leaf.text, match: t(leaf.result ? 'authorization.yes' : 'authorization.no'),
      })}</li>)}</ul></details></li>)}</ul>
    </Stack>}
  </SettingsSection>
}

export function AccessCoverage({ id }: { id: string }) {
  const t = useT()
  const { search, page: setPage, filter } = useSecureSearch()
  const query = useQuery(coverageOptions(id))
  const rows = query.data?.rows ?? []
  const entities = [...new Set(rows.map(item => item.entity))]
  const index = new Map(rows.map(row => [row.entity + '.' + row.op, row]))
  const detail = search.view ? index.get(search.view) : undefined
  const pages = Math.ceil(entities.length / 10)
  const page = Math.min(search.page ?? 1, Math.max(1, pages))
  function stateLabel(row: CoverageRow) { return t(`authorization.coverage_${row.state}`) }
  return <SettingsSection title={t('authorization.tab_coverage')} description={t('authorization.coverageHelp')}>
    {query.isPending ? <SecureLoading label={t('common.loading')} /> : query.isError ?
      <LoadFailure error={query.error} message={t('authorization.coverageError')} retry={() => void query.refetch()} /> :
      entities.length ? <>
        <Table label={t('authorization.tab_coverage')} columns={[{ id: 'entity', label: t('authorization.entity') },
          ...operations.map(value => ({ id: value, label: t(`authorization.op_${value}`) }))]}
          rows={entities.slice((page - 1) * 10, page * 10).map(entity => ({ id: entity, cells: [entity, ...operations.map(op => {
            const key = entity + '.' + op
            const row = index.get(key)
            return row ? <Button aria-label={t('authorization.coverageSlot', { entity, op: t(`authorization.op_${op}`), state: stateLabel(row) })}
              onClick={() => filter({ view: key }, false)}>{stateLabel(row)}</Button> : t('authorization.none')
          })] }))} />
        {pages > 1 && <Pagination page={page} pages={pages} label={t('authorization.tab_coverage')} onChange={setPage} />}
      </> : <EmptyState title={t('authorization.noEntities')} action={<SecureLink id={id} section="model" label={t('authorization.dataModel')} />} />}
    {detail && <Dialog open onOpenChange={open => { if (!open) filter({ view: undefined }, false) }}
      title={t('authorization.slotName', { entity: detail.entity, operation: t(`authorization.op_${detail.op}`) })}>
      <Badge>{stateLabel(detail)}</Badge>
      {(['allow', 'deny'] as const).map(effect => <Stack key={effect} gap={1}><h3>{t(`authorization.effect_${effect}`)}</h3>
        {detail[effect].length ? <ul>{detail[effect].map((item, i) => <li key={i}>
          {t('authorization.coverageDetail', { policy: item.policy, who: item.who,
            condition: item.unconditional ? t('authorization.always') : item.condition })}
        </li>)}</ul> : <p>{t('authorization.none')}</p>}
      </Stack>)}
    </Dialog>}
  </SettingsSection>
}
