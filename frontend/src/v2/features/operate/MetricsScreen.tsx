import { useQuery } from '@tanstack/react-query'
import { entitiesOf, groupDigits, presetOf, slotOf, unitOf } from '../../../shell/metrics/metricsLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Disclosure, EmptyState, Row, Stack, Table, Tabs } from '../../ui'
import {
  canWrite, errorInfo, metricsOptions, metricValueOptions, reportsOptions, reportValueOptions, runsOptions, specOptions, useMetricAction,
} from './api/operate'
import type { MetricAction, MetricRead, OperateProps, ReportMetricValue, ReportRead } from './api/operate'
import { LoadState, OperateScreen, RoleNotice, SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { calculationKey, MetricEditor, operatorKey, presetKey, ReportEditor } from './components/MetricEditors'
import './operate.css'

const newItem = ':new'
const historySize = 20

export default function MetricsScreen(props: OperateProps) {
  return <OperateScreen title={'operate.metrics.title'} lead="operate.metrics.lead"><Metrics {...props} /></OperateScreen>
}

function useActionMessage() {
  const t = useT()
  const date = useOperateDate()
  return (error: unknown) => {
    const message = errorInfo(error)
    if (!message) return t('common.actionFailed')
    if (message.status === 403) return t('behavior.forbidden')
    if (message.code === 'metric_in_use') return t('operate.metrics.metricInUse', { message: message.message })
    if (message.code === 'metric_too_large') return t('operate.metrics.tooLarge', { message: message.message })
    if (message.code === 'quota_exceeded') {
      const d = message.details[0] as { used?: number; limit?: number; period_end?: string } | undefined
      const usage = typeof d?.used === 'number' && typeof d.limit === 'number' ?
        t('operate.metrics.quotaUsage', { used: d.used, limit: d.limit }) : ''
      const reset = d?.period_end ? t('operate.metrics.quotaReset', { date: date(d.period_end) }) : ''
      return [t('operate.metrics.quota'), usage, reset].filter(Boolean).join(' ')
    }
    return t('operate.data', { value: message.message })
  }
}

function Metrics(props: OperateProps) {
  const { projectId: id } = props
  const t = useT()
  const m = (key: string) => t('operate.metrics.' + key)
  const date = useOperateDate()
  const actionMessage = useActionMessage()
  const { search, change } = useOperateSearch()
  const tab = search.tab === 'reports' ? 'reports' : 'metrics'
  const metrics = useQuery(metricsOptions(id))
  const reports = useQuery(reportsOptions(id))
  const spec = useQuery(specOptions(id))
  const action = useMetricAction(id)
  const writable = canWrite(props)
  const entities = spec.data ? entitiesOf(spec.data) : []
  const metricRows = metrics.data?.items ?? []
  const reportRows = reports.data?.items ?? []
  const editMetric = tab === 'metrics' ? metricRows.find(row => row.key === search.edit) : undefined
  const editReport = tab === 'reports' ? reportRows.find(row => row.id === search.edit) : undefined
  const opened = tab === 'reports' ? reportRows.find(row => row.id === search.report) : undefined

  const close = () => { action.reset(); change({ edit: undefined }) }
  const edit = (key: string) => { action.reset(); change({ edit: key }) }
  const switchTab = (tab: string) => { action.reset(); change({ tab, edit: undefined, report: undefined, history: undefined }) }
  const save = (request: MetricAction) => {
    action.mutate(request, { onSuccess: () => change({ edit: undefined }, true) })
  }
  const reload = async () => {
    const results = await Promise.all([metrics.refetch(), reports.refetch(), spec.refetch()])
    if (results.every(result => result.isSuccess)) action.reset()
  }
  const renderDelete = (type: 'metric-delete' | 'report-delete', key: string, name: string) => <ConfirmDestructive
    trigger={<Button variant="danger" disabled={action.isPending} aria-label={t('operate.metrics.deleteItem', { name })}>{t('operate.delete')}</Button>}
    title={t('operate.metrics.deleteTitle', { name })} description={m('deleteHelp')} action={t('operate.delete')}
    pending={action.isPending} error={action.variables?.type === type && action.variables.key === key && action.isError ? actionMessage(action.error) : undefined}
    onConfirm={async () => {
      await action.mutateAsync({ type, key })
      if (key === search.report || key === search.edit) change({
        report: key === search.report ? undefined : search.report, edit: key === search.edit ? undefined : search.edit, history: undefined,
      })
    }} />
  const showSaveError = action.isError && action.variables?.type !== 'metric-delete' && action.variables?.type !== 'report-delete'
  const conflict = showSaveError && errorInfo(action.error)?.status === 409
  const errors = [spec, metrics, reports].filter(query => query.isError)
  const cols = (keys: string[]) => keys.map(key => ({ id: key, label: m(key) }))
  const ready = spec.data && metrics.data && reports.data
  const refreshFailed = action.isSuccess && errors.length > 0
  return <Stack gap={4}>
    <RoleNotice {...props} />
    {showSaveError && (conflict ? <ConflictBanner onReload={() => void reload()}>{actionMessage(action.error)}</ConflictBanner> :
      <Alert tone="danger" action={action.variables?.type === 'report-run' ? <Button onClick={() => action.mutate(action.variables!)}>{t('common.retry')}</Button> : undefined}>
        {actionMessage(action.error)}
      </Alert>)}
    {action.isSuccess && !refreshFailed && <Alert tone="success">{t(action.variables?.type === 'report-run' ? 'operate.metrics.runSaved' : 'operate.savedNotice')}</Alert>}
    <Tabs label={m('tabs')} value={tab} onChange={switchTab} items={[
      { id: 'metrics', label: m('metrics'), content: ready && <Stack>
        <Row className="v2-spread"><p className="v2-muted">{t('operate.metrics.metricCount', { count: metrics.data?.total ?? 0 })}</p>
          {writable && <Button variant="primary" disabled={!entities.length || metricRows.length >= 100 || action.isPending}
            onClick={() => edit(newItem)}>{m('newMetric')}</Button>}</Row>
        {writable && (editMetric || search.edit === newItem) && <MetricEditor key={search.edit} existing={editMetric} entities={entities}
          metrics={metricRows} pending={action.isPending} error={action.error} close={close} save={save} />}
        {!metricRows.length ? <EmptyState title={m('noMetrics')} description={m('noMetricsHelp')} action={writable &&
          (entities.length ? <Button onClick={() => edit(newItem)}>{m('newMetric')}</Button> :
            <SectionLink id={id} section="model" label={t('operate.model')} />)} /> :
          <Table label={m('metrics')} columns={cols(['metric', 'value', 'definition', 'actions'])} rows={metricRows.map(metric => ({
            id: metric.key,
            cells: [
              <Stack gap={1}><strong>{t('operate.data', { value: metric.definition.label })}</strong>
                <code>{t('operate.data', { value: metric.key })}</code>
                <span className="v2-muted">{t('operate.version', { version: metric.version })}</span>
                <span className="v2-muted">{t('operate.updated', { date: date(metric.updated_at) })}</span></Stack>,
              <MetricValue id={id} metric={metric} />,
              <Definition metric={metric} />,
              writable ? <Row gap={1}><Button disabled={action.isPending} onClick={() => edit(metric.key)}>{t('operate.edit')}</Button>
                {renderDelete('metric-delete', metric.key, metric.definition.label)}</Row> : t('common.readOnly'),
            ],
          }))} />}
      </Stack> },
      { id: 'reports', label: m('reports'), content: ready && <Stack>
        <Row className="v2-spread"><p className="v2-muted">{t('operate.metrics.reportCount', { count: reports.data?.total ?? 0 })}</p>
          {writable && <Button variant="primary" disabled={!metricRows.length || reportRows.length >= 50 || action.isPending}
            onClick={() => edit(newItem)}>{m('newReport')}</Button>}</Row>
        {writable && (editReport || search.edit === newItem) && <ReportEditor key={search.edit} existing={editReport}
          metrics={metricRows} pending={action.isPending} error={action.error} close={close} save={save} />}
        {!reportRows.length ? <EmptyState title={m('noReports')} description={m(!metricRows.length ? 'needMetric' : 'noReportsHelp')}
          action={metricRows.length ? writable && <Button onClick={() => edit(newItem)}>{m('newReport')}</Button> :
            <Button onClick={() => switchTab('metrics')}>{m('metrics')}</Button>} /> :
          <Table label={m('reports')} columns={cols(['report', 'schedule', 'metrics', 'actions'])} rows={reportRows.map(report => {
            const preset = presetOf(report.schedule)
            return {
              id: report.id, cells: [
                <Stack gap={1}><strong>{t('operate.data', { value: report.name })}</strong>
                  <span className="v2-muted">{t('operate.updated', { date: date(report.updated_at) })}</span></Stack>,
                <Stack gap={1}><p>{t('operate.metrics.scheduleSummary', {
                  schedule: preset === 'custom' ? t('operate.metrics.customLabel', { cron: report.schedule }) : t(presetKey(preset)),
                  zone: report.timezone, status: t(report.enabled ? 'operate.on' : 'operate.metrics.paused'),
                })}</p>{report.last_scheduled_for && <p className="v2-muted">{t('operate.metrics.lastScheduled', { date: date(report.last_scheduled_for) })}</p>}</Stack>,
                t('operate.data', { value: report.metric_keys.join(', ') }),
                <Row gap={1}><Button aria-expanded={opened?.id === report.id} onClick={() =>
                  change({ report: opened?.id === report.id ? undefined : report.id, history: undefined })}>
                  {t(opened?.id === report.id ? 'operate.close' : 'operate.view')}</Button>
                  {writable && <><Button disabled={action.isPending} onClick={() => edit(report.id)}>{t('operate.edit')}</Button>
                    {renderDelete('report-delete', report.id, report.name)}</>}</Row>,
              ],
            }
          })} />}
        {opened && <ReportDetails id={id} report={opened} metrics={metricRows} writable={writable} pending={action.isPending}
          run={() => action.mutate({ type: 'report-run', key: opened.id })} />}
      </Stack> },
    ]} />
    {refreshFailed ? <ConflictBanner action={<Button onClick={() => void reload()}>{m('refreshNow')}</Button>}>{m('listRefresh')}</ConflictBanner> :
      errors.length > 0 ? <LoadState error={errors[0].error} retry={reload} /> : !ready && <LoadState retry={reload} />}
  </Stack>
}

function Definition({ metric }: { metric: MetricRead }) {
  const t = useT()
  const { definition } = metric
  const calculation = t(calculationKey(definition.agg))
  return <Stack gap={1}>
    <p>{t('operate.metrics.definitionSummary', { entity: definition.entity, calculation })}</p>
    <Disclosure label={t('operate.metrics.lineage')}><Stack gap={1}>
      <p>{t('operate.metrics.source', { entity: definition.entity, calculation })}</p>
      {definition.field && <p>{t('operate.metrics.fieldValue', { field: definition.field })}</p>}
      {definition.group_by && <p>{t('operate.metrics.groupValue', { field: definition.group_by })}</p>}
      {definition.filter?.map((filter, index) => <p key={index}>{t('operate.metrics.filterValue', {
        field: filter.field, operator: t(operatorKey(filter.op)), value: JSON.stringify(filter.value) ?? '',
      })}</p>)}
    </Stack></Disclosure>
  </Stack>
}

function FormatValue({ slot, unit }: { slot: ReportMetricValue; unit?: string | null }) {
  const t = useT()
  const fmt = (value: string | number | null | undefined) => value == null ? t('operate.metrics.noValue') :
    t(unit ? 'operate.metrics.withUnit' : 'operate.data', { value: groupDigits(String(value)), unit: unit ?? '' })
  if (slot.error) return <p>{slot.error === 'quota_exceeded' ? t('operate.metrics.storedQuota') :
    t('operate.metrics.storedError', { message: slot.error })}</p>
  if (!slot.groups?.length) return <strong>{fmt(slot.value)}</strong>
  return <dl className="v2-operate-kv">{slot.groups.map(({ key, value }, i) => <div key={i}>
    <dt>{key ? t('operate.data', { value: key }) : t('operate.metrics.noGroup')}</dt><dd>{fmt(value)}</dd>
  </div>)}</dl>
}

function MetricValue({ id, metric }: { id: string; metric: MetricRead }) {
  const query = useQuery(metricValueOptions(id, metric.key))
  const message = useActionMessage()
  const date = useOperateDate()
  const t = useT()
  if (query.isError) return <Alert tone="danger" action={<Button onClick={() => void query.refetch()}>{t('common.retry')}</Button>}>{message(query.error)}</Alert>
  if (!query.data) return <LoadState error={query.error} retry={query.refetch} lines={2} />
  return <Stack gap={1}><FormatValue slot={query.data} unit={metric.definition.unit} />
    <p className="v2-muted">{t('operate.computed', { date: date(query.data.computed_at) })}</p></Stack>
}

function ReportDetails({ id, report, metrics, writable, pending, run }: {
  id: string; report: ReportRead; metrics: MetricRead[]; writable: boolean; pending: boolean; run: () => void
}) {
  const t = useT()
  const date = useOperateDate()
  const m = (key: string) => t('operate.metrics.' + key)
  const { search, change } = useOperateSearch()
  const limit = Math.min(200, (search.history ?? 1) * historySize)
  const live = useQuery(reportValueOptions(id, report.id))
  const history = useQuery(runsOptions(id, report.id, limit))
  const runButton = writable && <Button variant="primary" disabled={pending} onClick={run}>{m('run')}</Button>
  const valueList = (values: Parameters<typeof slotOf>[0], keys: string[]) => <dl className="v2-operate-kv">
    {keys.map(key => <div key={key}><dt>{t('operate.data', { value: metrics.find(metric => metric.key === key)?.definition.label ?? key })}</dt>
      <dd><FormatValue slot={slotOf(values, key)} unit={unitOf(metrics, key)} /></dd></div>)}
  </dl>
  return <Stack>
    <SettingsSection title={m('live')} description={t('operate.data', { value: report.name })}>
      {runButton && <Row>{runButton}</Row>}
      {live.data ? <Stack>{valueList(live.data.values, report.metric_keys)}
        <p className="v2-muted">{t('operate.computed', { date: date(live.data.computed_at) })}</p></Stack> :
        <LoadState error={live.error} retry={live.refetch} lines={2} />}
    </SettingsSection>
    <SettingsSection title={m('history')}>
      {!history.data ? <LoadState error={history.error} retry={history.refetch} lines={2} /> :
        !history.data.items.length ? <EmptyState title={m('noRuns')} description={m('noRunsHelp')} action={runButton} /> : <Stack>
          <p>{t('operate.metrics.runsShowing', { count: history.data.items.length, total: history.data.total })}</p>
          <Table label={m('history')} columns={['schedule', 'statusHeading', 'value'].map(key => ({ id: key, label: m(key) }))}
            rows={history.data.items.map(run => ({ id: run.id, cells: [
              date(run.scheduled_for),
              <Badge tone={run.status === 'ok' ? 'success' : run.status === 'refused' ? 'warning' : 'neutral'}>
                {['ok', 'refused', 'running'].includes(run.status) ? m('status.' + run.status) : t('operate.data', { value: run.status })}
              </Badge>,
              valueList(run.values, Object.keys(run.values)),
            ] }))} />
          {history.data.total > history.data.items.length && limit < 200 && <Row><Button
            onClick={() => change({ history: (search.history ?? 1) + 1 })}>{m('moreRuns')}</Button></Row>}
        </Stack>}
    </SettingsSection>
  </Stack>
}
