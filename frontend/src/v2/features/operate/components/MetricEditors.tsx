import { useReducer } from 'react'
import type { FormEvent } from 'react'
import {
  AGGS, CRON_PRESETS, MAX_FILTERS, definitionToForm, emptyMetricForm, emptyReportForm, fieldsForAgg, formToDefinition, formToReport,
  opsFor, presetOf, reportToForm, scalarFields, toggleKey, validateMetricForm,
} from '../../../../shell/metrics/metricsLogic'
import type { SpecEntity } from '../../../../shell/metrics/metricsLogic'
import { useT } from '../../../i18n'
import { ConfirmDestructive, SettingsSection } from '../../../patterns'
import { Button, Card, Checkbox, Field, Grid, Input, Row, Select, Stack } from '../../../ui'
import { metricFilterValidation, metricTextValidation, reportValidation } from '../../../validators/operate'
import { errorInfo, fieldErrors } from '../api/operate'
import type { MetricAction, MetricRead, ReportRead } from '../api/operate'
import { useOptions } from './Common'
import { createDraft, createReportDraft, metricDraft, reportDraft } from '../state/metrics'

type EditorProps = {
  metrics: MetricRead[]
  pending: boolean
  error: unknown
  close: () => void
  save: (action: MetricAction) => void
}
const none = '__none'
const optionKey = (name: string, value: string) => 'operate.metrics.' + name + '.' + value

export function calculationKey(value: string) { return optionKey('agg', value) }
export function operatorKey(value: string) { return optionKey('op', value) }
export function presetKey(value: string) { return optionKey('preset', value) }

function focusError(form: HTMLFormElement, field: string) {
  form.querySelector<HTMLElement>('[data-metric-focus="' + CSS.escape(field) + '"]')?.focus()
}

function serverFieldErrors(error: unknown) {
  const result = Object.fromEntries(Object.entries(fieldErrors(error, 'definition')).map(([key, messages]) =>
    [key.replace(/^filter\.(\d+)(?:\..+)?$/, 'filter-$1'), messages.join(' ')]))
  const response = errorInfo(error)
  if (response?.status === 422) {
    const path = response.message.split(':', 1)[0]
    if (/^(key|label|entity|agg|field|group_by|unit|name|metric_keys|schedule|timezone|filter\[\d+\](?:\.\w+)?)$/.test(path)) {
      result[path.replace(/^filter\[(\d+)\](?:\.\w+)?$/, 'filter-$1')] = response.message
    }
  }
  return result
}

export function MetricEditor({ existing, entities, metrics, pending, error, close, save }: EditorProps & { existing?: MetricRead; entities: SpecEntity[] }) {
  const t = useT()
  const pick = useOptions()
  const m = (key: string) => t('operate.metrics.' + key)
  const [draft, dispatch] = useReducer(metricDraft, existing ? definitionToForm(existing.definition) : emptyMetricForm(entities[0]?.name), createDraft)
  const form = draft.value
  const entity = entities.find(item => item.name === form.entity)
  const fields = scalarFields(entity)
  const fieldType = (name: string) => fields.find(field => field.name === name)?.type ?? ''
  const errors = {
    ...Object.fromEntries(validateMetricForm(form, entities, Boolean(existing), metrics.map(metric => metric.key))
      .map(issue => [issue.field, t('operate.data', { value: issue.message })])),
    ...metricTextValidation(form, t),
  }
  if (form.group_by && !fields.some(field => field.name === form.group_by)) errors.group_by = t('operate.validation.metricGroup')
  if (!AGGS.some(item => item.id === form.agg)) errors.agg = t('operate.validation.metricAgg')
  form.filters.forEach((filter, index) => {
    const key = 'filter-' + index
    const type = fieldType(filter.field)
    const message = type ? metricFilterValidation(filter.value, filter.op, type, t) : t('operate.validation.filterField')
    if (message) errors[key] = message
  })
  const backend = serverFieldErrors(error)
  const issue = (field: string) => {
    const message = ((draft.submitted || draft.touched.includes(field)) && errors[field]) || backend[field]
    return message ? t('operate.data', { value: message }) : undefined
  }
  const touch = (field: string) => dispatch({ type: 'touch', field })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    dispatch({ type: 'submit' })
    const first = Object.keys(errors)[0]
    if (first) { focusError(event.currentTarget, first); return }
    save({ type: 'metric-save', key: existing?.key, definition: formToDefinition(form, entity) })
  }
  const allowedField = (agg: string) => fieldsForAgg(entity, agg).map(field => field.name)
  return <SettingsSection title={m(existing ? 'editMetric' : 'newMetric')}>
    <form noValidate onSubmit={submit} aria-busy={pending}><Stack>
      <Grid>
        <Field label={m('key')} error={issue('key')}>{attrs => <Input {...attrs} data-metric-focus="key" maxLength={60}
          value={form.key} readOnly={Boolean(existing) || pending} onBlur={() => touch('key')}
          onChange={event => dispatch({ type: 'update', value: { key: event.target.value } })} />}</Field>
        <Field label={m('name')} error={issue('label')}>{attrs => <Input {...attrs} data-metric-focus="label" maxLength={120}
          value={form.label} readOnly={pending} onBlur={() => touch('label')}
          onChange={event => dispatch({ type: 'update', value: { label: event.target.value } })} />}</Field>
        <Field label={m('entity')} error={issue('entity')}>{attrs => <Select disabled={pending}
          triggerProps={{ ...attrs, ...{ 'data-metric-focus': 'entity' }, onBlur: () => touch('entity') }} value={form.entity} placeholder={m('pick')}
          options={pick([...new Set([...entities.map(item => item.name), form.entity])])}
          onValueChange={value => dispatch({ type: 'update', value: { entity: value, field: '', group_by: '', filters: [] } })} />}</Field>
        <Field label={m('calculation')} error={issue('agg')}>{attrs => <Select disabled={pending}
          triggerProps={{ ...attrs, ...{ 'data-metric-focus': 'agg' } }} value={form.agg} options={AGGS.map(({ id }) => ({ value: id, label: t(calculationKey(id)) }))}
          onValueChange={agg => dispatch({ type: 'update', value: { agg, field: allowedField(agg).includes(form.field) ? form.field : '' } })} />}</Field>
        <Field label={m('field')} error={issue('field')}>{attrs => <Select disabled={pending} triggerProps={{ ...attrs, ...{ 'data-metric-focus': 'field' }, onBlur: () => touch('field') }}
          value={form.field || none} options={[{ value: none, label: m('noField') }, ...pick(allowedField(form.agg))]}
          onValueChange={value => dispatch({ type: 'update', value: { field: value === none ? '' : value } })} />}</Field>
        <Field label={m('group')} error={issue('group_by')}>{attrs => <Select disabled={pending} triggerProps={{ ...attrs, ...{ 'data-metric-focus': 'group_by' } }}
          value={form.group_by || none} options={[{ value: none, label: m('noGroupBy') }, ...pick(fields.map(field => field.name))]}
          onValueChange={value => dispatch({ type: 'update', value: { group_by: value === none ? '' : value } })} />}</Field>
        <Field label={m('unit')} error={issue('unit')}>{attrs => <Input {...attrs} data-metric-focus="unit" maxLength={30} value={form.unit} readOnly={pending}
          onBlur={() => touch('unit')} onChange={event => dispatch({ type: 'update', value: { unit: event.target.value } })} />}</Field>
      </Grid>
      <h3>{m('filters')}</h3>
      {form.filters.map((filter, index) => {
        const key = 'filter-' + index
        const name = t('operate.metrics.filter', { count: index + 1 })
        const action = t('operate.metrics.removeFilter', { count: index + 1 })
        return <Card key={index} role="group" aria-label={name}><Stack>
          <h4>{name}</h4>
          <Grid>
            <Field label={m('field')}>{attrs => <Select disabled={pending} triggerProps={attrs} value={filter.field} placeholder={m('pick')}
              options={pick(fields.map(field => field.name))}
              onValueChange={field => dispatch({ type: 'filter-update', index, value: { field, op: 'eq', value: '' } })} />}</Field>
            <Field label={m('operator')}>{attrs => <Select disabled={pending} triggerProps={attrs} value={filter.op}
              options={opsFor(fieldType(filter.field)).map(({ id }) => ({ value: id, label: t(operatorKey(id)) }))}
              onValueChange={op => dispatch({ type: 'filter-update', index, value: { op } })} />}</Field>
            <Field label={m('value')} error={issue(key)}>{attrs => <Input {...attrs} data-metric-focus={key} value={filter.value} readOnly={pending}
              onBlur={() => touch(key)} onChange={event => dispatch({ type: 'filter-update', index, value: { value: event.target.value } })} />}</Field>
          </Grid>
          <Row><ConfirmDestructive trigger={<Button disabled={pending} variant="danger">{action}</Button>}
            title={action} description={m('filterRemoveHelp')} action={m('remove')} onConfirm={() => dispatch({ type: 'filter-remove', index })} /></Row>
        </Stack></Card>
      })}
      <Row><Button disabled={pending || form.filters.length >= MAX_FILTERS || !fields.length}
        onClick={() => dispatch({ type: 'filter-add', filter: { field: fields[0].name, op: 'eq', value: '' } })}>{m('addFilter')}</Button></Row>
      <Row><Button variant="primary" type="submit" disabled={pending}>{m('saveMetric')}</Button>
        <Button disabled={pending} onClick={close}>{t('operate.close')}</Button></Row>
    </Stack></form>
  </SettingsSection>
}

export function ReportEditor({ existing, metrics, pending, error, close, save }: EditorProps & { existing?: ReportRead }) {
  const t = useT()
  const m = (key: string) => t('operate.metrics.' + key)
  const [draft, dispatch] = useReducer(reportDraft, existing ? reportToForm(existing) : emptyReportForm(), createReportDraft)
  const form = draft.value
  const custom = draft.custom ?? presetOf(form.schedule) === 'custom'
  const errors = reportValidation(form, t)
  const backend = serverFieldErrors(error)
  const touch = (field: string) => dispatch({ type: 'touch', field })
  const issue = (field: string) => {
    const message = ((draft.submitted || draft.touched.includes(field)) && errors[field]) || backend[field]
    return message ? t('operate.data', { value: message }) : undefined
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    dispatch({ type: 'submit' })
    const first = Object.keys(errors)[0]
    if (first) { focusError(event.currentTarget, first); return }
    save({ type: 'report-save', key: existing?.id, body: formToReport(form) })
  }
  return <SettingsSection title={m(existing ? 'editReport' : 'newReport')}>
    <form noValidate onSubmit={submit} aria-busy={pending}><Stack>
      <Grid>
        <Field label={m('name')} error={issue('name')}>{attrs => <Input {...attrs} data-metric-focus="name" maxLength={120}
          value={form.name} readOnly={pending} onBlur={() => touch('name')} onChange={event => dispatch({ type: 'update', value: { name: event.target.value } })} />}</Field>
        <Field label={m('schedule')} error={!custom && issue('schedule')}>{attrs => <Select disabled={pending} triggerProps={attrs}
          options={[...CRON_PRESETS.map(item => ({ value: item.id, label: t(presetKey(item.id)) })), { value: 'custom', label: m('custom') }]}
          value={custom ? 'custom' : presetOf(form.schedule)}
          onValueChange={value => dispatch({ type: 'update', custom: value === 'custom',
            value: { schedule: CRON_PRESETS.find(item => item.id === value)?.cron ?? form.schedule } })} />}</Field>
        {custom && <Field label={m('cron')} hint={t('operate.jobs.cron')} error={issue('schedule')}>{attrs => <Input {...attrs}
          data-metric-focus="schedule" maxLength={100} value={form.schedule} readOnly={pending}
          onBlur={() => touch('schedule')} onChange={event => dispatch({ type: 'update', custom: true, value: { schedule: event.target.value } })} />}</Field>}
        <Field label={m('zone')} error={issue('timezone')}>{attrs => <Input {...attrs} data-metric-focus="timezone" maxLength={64}
          value={form.timezone} readOnly={pending} onBlur={() => touch('timezone')}
          onChange={event => dispatch({ type: 'update', value: { timezone: event.target.value } })} />}</Field>
      </Grid>
      <Stack role="group" aria-label={m('metrics')}>
        <h3>{m('metrics')}</h3>
        <Grid>{metrics.map((metric, index) => <Checkbox key={metric.key} data-metric-focus={index === 0 ? 'metric_keys' : undefined}
          label={t('operate.data', { value: metric.definition.label })} checked={form.metric_keys.includes(metric.key)}
          disabled={pending || form.metric_keys.length >= 20 && !form.metric_keys.includes(metric.key)}
          onBlur={() => touch('metric_keys')} onChange={() => dispatch({ type: 'update', value: { metric_keys: toggleKey(form.metric_keys, metric.key) } })} />)}</Grid>
        {issue('metric_keys') && <span className="v2-field-error" role="alert">{issue('metric_keys')}</span>}
      </Stack>
      <Checkbox label={t('operate.enabled')} checked={form.enabled} disabled={pending}
        onChange={event => dispatch({ type: 'update', value: { enabled: event.target.checked } })} />
      <Row><Button variant="primary" type="submit" disabled={pending}>{m('saveReport')}</Button>
        <Button disabled={pending} onClick={close}>{t('operate.close')}</Button></Row>
    </Stack></form>
  </SettingsSection>
}
