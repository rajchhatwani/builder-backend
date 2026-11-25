import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useReducer } from 'react'
import { useLanguage, useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, Form, PageHeader } from '../../patterns'
import type { SectionSearch } from '../../projectNavigation'
import { Alert, Badge, Button, Card, DesktopOnlyCard, Disclosure, EmptyState, Field, Input, Pagination, Row, Select, Stack, Table, Tabs, Textarea } from '../../ui'
import { importFileIssue, parseSchemaObject } from '../../validators'
import { errorText, specOptions, statusOf } from './api/connect'
import type { ConnectProps, ConnectSpec } from './api/connect'
import { exportImportCsv, historySize, importBatchOptions, importHistoryOptions, importQuota, importRecordsOptions, importResultOptions, importRowsOptions, recordSize, reviewSize, useImportAction } from './api/imports'
import type { ImportPreview, ImportRow } from './api/imports'
import { BlockLoad, BlockRole, SectionLink } from './components/BlockStatus'
import { importDraftReducer } from './state/importDraft'

type Entity = ConnectSpec['entities'][number]
type Change = (values: SectionSearch) => void
type Write = ReturnType<typeof useImportAction>
const statuses = ['rejected', 'duplicate', 'fixed', 'accepted', 'all'] as const
const mappingSkip = '__v2_skip__'
const statusKey = (status: string) => 'connectB.import.status.' + status

function useImportNavigation() {
  const search = useSearch({ from: '/projects/$projectId/$section' })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const change: Change = values => void navigate({ search: previous => ({ ...previous, ...values }) })
  return { search, change }
}

export default function ImportScreen(props: ConnectProps) {
  const t = useT()
  const { projectId: id, role, rolePending, organizationSlug } = props
  const { search, change } = useImportNavigation()
  const spec = useQuery(specOptions(id))
  const readOnly = !role || role === 'viewer' || Boolean(rolePending)
  const entities = spec.data?.entities ?? []
  const tab = search.tab === 'history' ? 'history' : 'wizard'
  return <Stack>
    <PageHeader title={t('connectB.import.title')} description={t('connectB.import.intro')} />
    <BlockRole {...props} />
    {!spec.data ? <BlockLoad error={spec.error} retry={() => void spec.refetch()} errorKey="connectB.import.error" /> :
      <Tabs label={t('connectB.import.tabs')} value={tab} onChange={tab => change({ tab, page: undefined })}
        items={[
          { id: 'wizard', label: t('connectB.import.wizard'), content: tab === 'wizard' && (search.batch ?
            <BatchView key={search.batch} id={id} batchId={search.batch} entities={entities} readOnly={readOnly} change={change} search={search} /> :
            <Upload id={id} entities={entities} readOnly={readOnly} entityName={search.entity} change={change} />) },
          { id: 'history', label: t('connectB.import.history'), content: tab === 'history' &&
            <History id={id} page={search.page ?? 1} change={change} /> },
        ]} />}
    <Card><Disclosure label={t('connectB.import.processing')}><Stack>
      <p>{t('connectB.import.flow')}</p><p>{t('connectB.import.quota')}</p>
      {organizationSlug && <Row><Button asChild><Link to="/org/$slug" params={{ slug: organizationSlug }}
        search={{ tab: 'usage' }}>{t('connectB.import.usage')}</Link></Button></Row>}
    </Stack></Disclosure></Card>
  </Stack>
}

function ImportProblem({ error, retry }: { error: unknown; retry: () => void }) {
  const t = useT()
  if (!error) return null
  if (statusOf(error) === 409) return <ConflictBanner onReload={retry} />
  const quota = importQuota(error)
  if (quota) {
    const metric = t('connectB.import.quotaMetric.' + quota.metric)
    return <Alert tone="warning">
      {quota.limit === undefined || quota.used === undefined ? t('connectB.import.quotaUsed', { metric }) :
        t('connectB.import.quotaDetail', { limit: quota.limit, used: quota.used, metric })}
      {quota.reset && <p>{t('connectB.import.quotaReset', { date: quota.reset })}</p>}
      <p>{t('connectB.import.quotaRecovery')}</p>
    </Alert>
  }
  if (statusOf(error) === 403) return <Alert tone="warning">{t('behavior.forbidden')}</Alert>
  return <div data-testid="import-error"><Alert tone="danger">{t('common.serverText', {
    text: errorText(error) ?? t('common.actionFailed'),
  })}</Alert></div>
}

function Upload({ id, entities, readOnly, entityName, change }: { id: string; entities: Entity[]; readOnly: boolean; entityName?: string; change: Change }) {
  const t = useT()
  const write = useImportAction(id)
  const entity = entities.find(item => item.name === entityName) ?? entities[0]
  if (!entity) return <div data-testid="import-empty"><EmptyState title={t('connectB.import.noEntities')}
    description={t('connectB.import.noEntitiesHelp')}
    action={<SectionLink projectId={id} section="model" label={t('connectB.import.openModel')} />} /></div>
  if (readOnly) return <EmptyState title={t('connectB.import.readOnly')}
    action={<Button onClick={() => change({ tab: 'history' })}>{t('connectB.import.history')}</Button>} />
  return <Card><Stack>
    <ImportSteps current="fileStep" />
    <h2>{t('connectB.import.fileStep')}</h2>
    <ImportProblem error={write.error} retry={write.reset} />
    <Form key={entity.name} pending={write.isPending} submitLabel={t('connectB.import.upload')}
      fields={[
        { name: 'entity', label: t('connectB.import.entity'), control: ({ disabled, ...attrs }) => <Select
          triggerProps={attrs} disabled={disabled} value={entity.name}
          options={entities.map(({ name }) => ({ value: name, label: t('schema.option', { value: name }) }))}
          onValueChange={entity => change({ entity })} /> },
        { name: 'file', label: t('connectB.import.file'), hint: t('connectB.import.fileHelp'),
          validateWith: (_, data) => {
            const file = data.get('file')
            const key = importFileIssue(file instanceof File ? file : undefined)
            return key ? { key } : undefined
          },
          control: attrs => <Input {...attrs} type="file" accept=".csv,text/csv" /> },
        { name: 'mapping', label: t('connectB.import.optionalMapping'), hint: t('connectB.import.optionalMappingHelp'),
          validate: [raw => {
            if (!raw.trim()) return
            const parsed = parseSchemaObject(raw)
            return raw.length > 20_000 || parsed.error || Object.entries(parsed.value ?? {}).some(([field, header]) =>
              !entity.fields.some(item => item.name === field) || typeof header !== 'string' || !header.trim())
              ? { key: 'connectB.import.mappingInvalid' } : undefined
          }], control: attrs => <Textarea {...attrs} /> },
      ]}
      onSubmit={values => {
        const file = values.get('file')
        if (!(file instanceof File)) return
        const raw = String(values.get('mapping') ?? '').trim()
        const mapping = raw ? parseSchemaObject(raw).value as Record<string, string> : undefined
        void write.mutateAsync({ type: 'upload', entity: entity.name, file, mapping }).then(({ preview }) => {
          if (preview) change({ batch: preview.batch_id, view: 'mapping', page: undefined, kind: undefined })
        }, () => undefined)
      }} />
  </Stack></Card>
}

function History({ id, page, change }: { id: string; page: number; change: Change }) {
  const { t, language } = useLanguage()
  const history = useQuery(importHistoryOptions(id, page))
  if (!history.data || history.isError) return <BlockLoad error={history.error} retry={() => void history.refetch()} errorKey="connectB.import.historyError" />
  const { items, total } = history.data
  return items.length || page > 1 ? <Card><Stack>
    <h2>{t('connectB.import.history')}</h2>
    <Table label={t('connectB.import.history')} columns={['file', 'entity', 'statusLabel', 'createdAt', 'committedAt', 'details', 'actions']
      .map(id => ({ id, label: t('connectB.import.' + id) }))}
      rows={items.map(batch => ({ id: batch.id, cells: [
        batch.filename, batch.entity, t(statusKey(batch.status)), date(batch.created_at, language), date(batch.committed_at, language),
        <Disclosure label={t('connectB.import.details')}><Stack>
          <p>{t('connectB.import.hash', { hash: batch.content_sha256 })}</p>
          <p>{t('connectB.import.mappingSummary', { mapping: pairs(batch.mapping) })}</p>
          {batch.counts.commit ? <p>{t('connectB.import.result', batch.counts.commit)}</p> : <Summary counts={batch.counts} />}
        </Stack></Disclosure>,
        <Button onClick={() => change({ tab: 'wizard', batch: batch.id, entity: batch.entity, view: 'mapping', page: undefined, recordPage: undefined, kind: undefined })}>
          {t(batch.status === 'previewed' ? 'connectB.import.resume' : 'connectB.import.openBatch')}</Button>,
      ] }))} />
    <Pagination label={t('connectB.import.history')} page={page} pages={Math.max(page, Math.ceil(total / historySize))}
      onChange={page => change({ page })} />
  </Stack></Card> : <EmptyState title={t('connectB.import.noHistory')}
    action={<Button onClick={() => change({ tab: 'wizard', batch: undefined })}>{t('connectB.import.wizard')}</Button>} />
}

const date = (value: string | null, language: string) => value ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : ''
const pairs = (values: Record<string, unknown>) => Object.entries(values).map(([key, value]) =>
  key + ': ' + (typeof value === 'string' ? value : JSON.stringify(value))).join(', ')

function ImportSteps({ current }: { current: string }) {
  const t = useT()
  return <ol className="v2-step-list" aria-label={t('connectB.import.steps')}>
    {['fileStep', 'mappingStep', 'review', 'doneStep'].map(step =>
      <li key={step} aria-current={step === current ? 'step' : undefined}>{t('connectB.import.' + step)}</li>)}
  </ol>
}

function Summary({ counts }: { counts: ImportPreview['counts'] }) {
  const t = useT()
  return <p role="status">{t('connectB.import.summary', { total: counts.total, ready: counts.accepted + counts.fixed,
    rejected: counts.rejected, duplicate: counts.duplicate })}</p>
}

function BatchView({ id, batchId, entities, readOnly, change, search }: {
  id: string; batchId: string; entities: Entity[]; readOnly: boolean; change: Change; search: SectionSearch
}) {
  const t = useT()
  const query = useQuery(importBatchOptions(id, batchId))
  const write = useImportAction(id)
  const batch = query.data
  const startOver = () => change({ batch: undefined, view: undefined, page: undefined, recordPage: undefined, kind: undefined })
  if (!batch) return <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectB.import.batchError" />
  const entity = entities.find(item => item.name === batch.entity)
  if (batch.status === 'committed') return <Records id={id} batch={batch} page={search.recordPage ?? 1} change={change} startOver={startOver} />
  if (batch.status === 'cancelled') return <EmptyState title={t(statusKey('cancelled'))}
    action={<Button onClick={startOver}>{t('connectB.import.another')}</Button>} />
  const review = search.view === 'review'
  const disabled = readOnly || write.isPending || statusOf(write.error) === 409
  return <Stack>
    <ImportSteps current={review ? 'review' : 'mapping'} />
    <Summary counts={batch.counts} />
    {query.isRefetchError && <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectB.import.batchError" />}
    <ImportProblem error={write.error} retry={() => { void query.refetch().then(result => { if (result.isSuccess) write.reset() }) }} />
    {review ? <Review id={id} batch={batch} entity={entity} disabled={disabled} search={search} change={change} write={write} /> :
      <Stack>
        <div className="v2-phone-only"><DesktopOnlyCard /></div>
        <div className="v2-phone-hidden"><Mapping key={JSON.stringify(batch.mapping)} batch={batch} entity={entity}
          disabled={disabled} change={change} write={write} /></div>
      </Stack>}
    <Row>
      {review && <Button onClick={() => change({ view: 'mapping', page: undefined })}>{t('connectB.import.back')}</Button>}
      {!readOnly && <ConfirmDestructive
        trigger={<Button variant="danger" disabled={disabled}>{t('connectB.import.cancel')}</Button>}
        title={t('connectB.import.cancel')} description={t('connectB.import.cancelHelp')} action={t('connectB.import.cancel')}
        onConfirm={async () => { await write.mutateAsync({ type: 'cancel', batch: batchId }); startOver() }} />}
    </Row>
  </Stack>
}

function Mapping({ batch, entity, disabled, change, write }: {
  batch: ImportPreview; entity?: Entity; disabled: boolean; change: Change; write: Write
}) {
  const t = useT()
  const [draft, dispatch] = useReducer(importDraftReducer, { mapping: batch.mapping, changed: false })
  const choose = () => change({ view: 'review', page: undefined, kind: undefined })
  const save = async () => {
    await write.mutateAsync({ type: 'mapping', batch: batch.batch_id, mapping: draft.mapping })
    choose()
  }
  const columns = entity?.fields ?? []
  const label = t('connectB.import.columns', { entity: batch.entity })
  return <Stack>
    <Card><Stack>
      <h2>{label}</h2>
      {columns.map(field => <Field key={field.name} label={t('connectB.import.column', { field: field.name })}
        hint={field.required && !draft.mapping[field.name] ? t('connectB.import.missingRequired') : undefined}>
        {attrs => <Select triggerProps={attrs} disabled={disabled}
          value={draft.mapping[field.name] == null ? mappingSkip : 'header:' + draft.mapping[field.name]}
          options={[{ value: mappingSkip, label: t('connectB.import.skipColumn') }, ...batch.headers.map(header =>
            ({ value: 'header:' + header, label: t('schema.option', { value: header }) }))]}
          onValueChange={value => dispatch({ type: 'map', field: field.name, header: value === mappingSkip ? null : value.slice(7) })} />}
      </Field>)}
      <Row>
        {draft.changed ? <ConfirmDestructive trigger={<Button variant="danger" disabled={disabled}>{t('connectB.import.continue')}</Button>}
          title={t('connectB.import.confirmMapping')} description={t('connectB.import.confirmMappingHelp')}
          action={t('connectB.import.applyMapping')} onConfirm={save} /> :
          <Button variant="primary" onClick={choose}>{t('connectB.import.continue')}</Button>}
      </Row>
    </Stack></Card>
    <Card><Stack>
      <h2>{t('connectB.import.sample')}</h2>
      <Table label={t('connectB.import.sample')} columns={[{ id: 'number', label: t('connectB.import.row') },
        ...batch.headers.map(header => ({ id: 'header:' + header, label: t('schema.option', { value: header }) })),
        { id: 'result', label: t('connectB.import.statusLabel') }]} rows={batch.sample.map(row => ({
        id: row.id, cells: [t('connectB.import.number', { number: row.row_no }), ...batch.headers.map(header => row.raw[header]), t(statusKey(row.status))],
      }))} />
    </Stack></Card>
  </Stack>
}

function Review({ id, batch, entity, disabled, search, change, write }: {
  id: string; batch: ImportPreview; entity?: Entity; disabled: boolean; search: SectionSearch; change: Change; write: Write
}) {
  const t = useT()
  const status = statuses.find(status => status === search.kind) ?? 'rejected'
  const page = search.page ?? 1
  const rows = useQuery(importRowsOptions(id, batch.batch_id, status, page))
  const ready = batch.counts.accepted + batch.counts.fixed
  return <Card><Stack>
    <h2>{t('connectB.import.review')}</h2>
    <Field label={t('connectB.import.filter')}>{attrs => <Select triggerProps={attrs} value={status}
      options={statuses.map(value => ({ value, label: t(statusKey(value)) }))}
      onValueChange={kind => change({ kind, page: undefined })} />}</Field>
    {!rows.data || rows.isError ? <BlockLoad error={rows.error} retry={() => void rows.refetch()} errorKey="connectB.import.rowsError" /> :
      <>
        {rows.data.items.length ? rows.data.items.map(row => <ReviewRow key={row.id} row={row} entity={entity} batch={batch}
          disabled={disabled} write={write} onDuplicate={() => change({ kind: 'duplicate', page: undefined })} />) :
          <EmptyState title={t('connectB.import.noRows')} />}
        <Pagination label={t('connectB.import.review')} page={page} pages={Math.max(page, Math.ceil(rows.data.total / reviewSize))}
          onChange={page => change({ page })} />
      </>}
    {!disabled && ready > 0 && <Row><ConfirmDestructive
      trigger={<Button variant="danger">{t('connectB.import.commitRows', { count: ready })}</Button>}
      title={t('connectB.import.commitRows', { count: ready })} description={t('connectB.import.commitHelp')}
      action={t('connectB.import.commitRows', { count: ready })}
      onConfirm={async () => { await write.mutateAsync({ type: 'commit', batch: batch.batch_id }) }} /></Row>}
  </Stack></Card>
}

function ReviewRow({ row, entity, batch, disabled, write, onDuplicate }: {
  row: ImportRow; entity?: Entity; batch: ImportPreview; disabled: boolean; write: Write; onDuplicate: () => void
}) {
  const t = useT()
  const problems = row.errors.filter(error => error.field)
  const canFix = row.status === 'rejected' || row.status === 'fixed' || row.errors.some(error => error.code === 'import_duplicate_after_fix')
  const fields = entity?.fields.filter(field => batch.mapping[field.name] ||
    problems.some(error => error.field === field.name)) ?? []
  return <Card><Stack>
    <Row><h3>{t('connectB.import.rowHeading', { number: row.row_no })}</h3><Badge>{t(statusKey(row.status))}</Badge></Row>
    {row.errors.length > 0 && <ul>{row.errors.map((error, index) => <li key={index}>{t(error.field ? 'connectB.import.fieldProblem' : 'common.serverText', {
      field: error.field, message: error.message, text: error.message,
    })}</li>)}</ul>}
    {(!canFix || disabled || !fields.length) && <p>{t('connectB.import.rowValues', { values: pairs(row.record ?? row.raw) })}</p>}
    {canFix && fields.length > 0 && <Form readOnly={disabled} submitLabel={t('connectB.import.saveRow', { number: row.row_no })}
      fields={fields.map(field => ({ name: field.name, label: t('connectB.import.fixField', { field: field.name, number: row.row_no }),
        control: attrs => <Input {...attrs} defaultValue={row.record && row.record[field.name] != null ?
          String(typeof row.record[field.name] === 'object' ? JSON.stringify(row.record[field.name]) : row.record[field.name]) :
          row.raw[batch.mapping[field.name]] ?? ''} /> }))}
      onSubmit={values => void write.mutateAsync({ type: 'fix', batch: batch.batch_id, row: row.id,
        values: Object.fromEntries(fields.map(field => [field.name, String(values.get(field.name) ?? '')])),
      }).then(result => { if (result.row?.errors.some(error => error.code === 'import_duplicate_after_fix')) onDuplicate() }, () => undefined)} />}
  </Stack></Card>
}

function Records({ id, batch, page, change, startOver }: { id: string; batch: ImportPreview; page: number; change: Change; startOver: () => void }) {
  const { t, language } = useLanguage()
  const result = useQuery(importResultOptions(id, batch.batch_id))
  const records = useQuery(importRecordsOptions(id, batch.entity, page))
  const download = useMutation({ mutationFn: () => exportImportCsv(id, batch.entity) })
  const label = t('connectB.import.records')
  return <Card><Stack>
    <ImportSteps current="doneStep" />
    <h2>{t('connectB.import.done')}</h2>
    {result.data ? <Alert tone="success">{t('connectB.import.result', { ...result.data })}</Alert> : <Summary counts={batch.counts} />}
    {!records.data || records.isError ? <BlockLoad error={records.error} retry={() => void records.refetch()} errorKey="connectB.import.recordsError" /> :
      <Stack>
        <p>{t('connectB.import.recordTotal', { total: records.data.total })}</p>
        {records.data.items.length > 0 && <Table label={label} columns={['details', 'createdAt', 'batch'].map(id => ({ id, label: t('connectB.import.' + id) }))}
          rows={records.data.items.map(row => ({ id: row.id, cells: [pairs(row.data), date(row.created_at, language), row.batch_id] }))} />}
        <Pagination label={label} page={page} pages={Math.max(page, Math.ceil(records.data.total / recordSize))}
          onChange={recordPage => change({ recordPage })} />
      </Stack>}
    {download.isError && <ImportProblem error={download.error} retry={() => download.mutate()} />}
    {download.isSuccess && (download.data || (records.data?.total ?? 0) > 10_000) && <Alert tone="warning">{t('connectB.import.truncated')}</Alert>}
    <Row>
      <Button disabled={download.isPending} onClick={() => download.mutate()}>{t('connectB.import.export')}</Button>
      <Button onClick={startOver}>{t('connectB.import.another')}</Button>
    </Row>
  </Stack></Card>
}
