import { useT } from '../../i18n'
import { Form } from '../../patterns'
import { Button, Row, Stack } from '../../ui'
import { noNullIssue, signedWholeIssue } from '../../validators/operateRuntime'
import { formatBp, formatMilli, parseFeatures, parseKind } from '../../../shell/operations/opsLogic'
import { useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { canWrite } from './api/operate'
import { recordPath } from './api/tools'
import type { PredictBody, Prediction, PredictionStats } from './api/tools'
import { useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Details, Empty, field, Filter, key, optional, Pager, Panel, Pick, Refresh, RuntimeState, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { JsonDetails, PageSize, ToolsLinks, useListSize } from './components/RuntimeTools'
import { ToolScreen } from './components/ToolScreen'

export default function PredictionScreen(props: LiveProps) {
  return <ToolScreen id={props} title={'prediction'}>{session => <PredictionBody session={session} writable={canWrite(props)} />}</ToolScreen>
}

const estimate = (t: ReturnType<typeof useT>, record: Prediction) => t(key('unitValue'), { value: record.value, unit: record.unit })
const interval = (t: ReturnType<typeof useT>, record: Prediction) => t(key('intervalRange'), { low: record.low, high: record.high })

function PredictionBody({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const { size, pickSize } = useListSize(100)
  const page = search.page ?? 1
  const query = useRuntimeQuery<Page<Prediction>>(session, '/prediction/records', {
    limit: size, offset: (page - 1) * size, kind: search.kind, subject_ref: search.subject,
    has_actual: search.status === 'recorded' ? true : search.status === 'stillMissing' ? false : undefined,
  })
  const selection = useRuntimeQuery<Prediction>(session, recordPath(search.edit ?? ''), {}, !!search.edit)
  return <Stack gap={4}>
    <ToolsLinks session={session} sections={['predictionsettings']} />
    <Accuracy session={session} />
    {writable && <Predict session={session} />}
    <Panel title={'predictionRecords'}>
      <Form key={JSON.stringify([search.kind, search.subject])} fields={[
        field(t, 'kind', { value: search.kind, max: 32, validate: value => value && !parseKind(value) ? { key: key('predictionKindError') } : undefined }),
        field(t, 'subject', { label: 'subjectRef', value: search.subject, max: 128, validate: noNullIssue }),
      ]} submitLabel={t(key('apply'))} onSubmit={form => change({ kind: optional(form, 'kind'), subject: optional(form, 'subject'), page: undefined })} />
      <Row><Pick label={t(key('actual'))} value={search.status ?? ''} options={choices(t, ['recorded', 'stillMissing'])}
        onChange={status => change({ status: status || undefined, page: undefined })} />
        <PageSize value={size} onChange={pickSize} /><Refresh run={query.refetch} /></Row>
      {query.isPending || query.isError ? <RuntimeState error={query.error} retry={query.refetch} /> :
        query.data.items.length ? <Columns label={'predictionRecords'} names={['when', 'kind', 'subjectRef', 'predicted', 'interval', 'actual']}
          rows={query.data.items.map(row => ({
            id: row.id, cells: [date(row.created_at), data(t, row.kind),
              <Button aria-expanded={search.edit === row.id} onClick={() => change({ edit: search.edit === row.id ? undefined : row.id })}>{data(t, row.subject_ref)}</Button>,
              estimate(t, row), interval(t, row), row.actual === null ? writable ? <Actual session={session} record={row} /> : t(key('enum.stillMissing')) :
                t(key('unitValue'), { value: row.actual, unit: row.unit })],
          }))} /> : <Empty message="noPredictions" onAction={query.refetch} />}
      <Pager label={'predictionRecords'} page={page} size={size} total={query.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.edit && <Panel title={'predictionDetail'}>
      {selection.isPending || selection.isError ? <RuntimeState error={selection.error} retry={selection.refetch} /> : <PredictionDetail record={selection.data} />}
    </Panel>}
  </Stack>
}

function Accuracy({ session }: { session: Session }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const stats = useRuntimeQuery<PredictionStats>(session, '/prediction/stats', { kind: search.kind, model_id: search.model })
  const result = stats.data
  return <Panel title={'accuracy'}>
    <Row><Filter name="model" max={64} value={search.model} onChange={model => change({ model })} /><Refresh run={stats.refetch} /></Row>
    {stats.isPending || stats.isError ? <RuntimeState error={stats.error} retry={stats.refetch} lines={3} /> :
      result && <Details values={[
        ['logged', data(t, result.logged)], ['withActual', data(t, result.with_actual)], ['mae', data(t, formatMilli(result.mae_milli))],
        ['absError', data(t, result.abs_error_sum)], ['covered', data(t, result.covered)], ['coverage', data(t, formatBp(result.coverage_bp))],
      ]} />}
  </Panel>
}

function Predict({ session }: { session: Session }) {
  const t = useT()
  const request = useRuntimeWrite<PredictBody, Prediction>(session, '/prediction/predict')
  return <Panel title={'makePrediction'}>
    <Form fields={[
      field(t, 'kind', { required: true, max: 32, validate: value => parseKind(value) ? undefined : { key: key('predictionKindError') } }),
      field(t, 'subject_ref', { label: 'subjectRef', required: true, max: 128, validate: noNullIssue }),
      { ...field(t, 'features', { area: true, max: 16500, validate: value => {
        const result = parseFeatures(value)
        return result.ok ? undefined : { key: key('value'), values: { value: result.error } }
      } }), hint: t(key('featureHelp')) },
    ]} pending={request.isPending} submitLabel={t(key('predictRun'))} serverErrors={serverFields(request.error, {}, path => path.startsWith('features.') ? 'features' : undefined)}
      onSubmit={form => {
        const result = parseFeatures(text(form, 'features'))
        if (result.ok) request.mutate({ kind: text(form, 'kind'), subject_ref: text(form, 'subject_ref'), features: result.features })
      }} />
    <WriteStatus error={request.error} reload={request.reset} success={request.data ? t(key('predictionSaved')) : undefined} />
    {request.data && <PredictionDetail record={request.data.data} />}
  </Panel>
}

function Actual({ session, record }: { session: Session; record: Prediction }) {
  const t = useT()
  const request = useRuntimeWrite<{ actual: number }, Prediction>(session, `${recordPath(record.id)}/actual`)
  return <Stack>
    <Form fields={[{ ...field(t, 'actual', { max: 17, validate: signedWholeIssue }), label: t(key('actualFor'), { subject: record.subject_ref }) }]}
      pending={request.isPending} submitLabel={t(key('recordActual'))} serverErrors={serverFields(request.error)}
      onSubmit={form => request.mutate({ actual: Number(text(form, 'actual')) })} />
    <WriteStatus error={request.error} reload={request.reset} />
  </Stack>
}

function PredictionDetail({ record }: { record: Prediction }) {
  const t = useT()
  const date = useOperateDate()
  return <Stack><Details values={[
    ['recordId', data(t, record.id)], ['model', data(t, record.model_id)], ['kind', data(t, record.kind)], ['subjectRef', data(t, record.subject_ref)],
    ['predicted', estimate(t, record)], ['interval', interval(t, record)], ['created', date(record.created_at)],
    ['actual', record.actual === null ? t(key('enum.stillMissing')) : t(key('unitValue'), { value: record.actual, unit: record.unit })],
    ['recordedAt', date(record.actual_at)],
    ...(record.actual === null ? [] : [
      ['predictionError', data(t, (BigInt(record.actual) - BigInt(record.value)).toLocaleString())],
      ['coverage', t(key(record.actual >= record.low && record.actual <= record.high ? 'insideInterval' : 'outsideInterval'))],
    ] as [string, string][]),
  ]} /><JsonDetails label={'features'} value={record.features} /></Stack>
}
