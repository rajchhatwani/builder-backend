import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, Form, PageHeader } from '../../patterns'
import { Alert, Badge, Button, Disclosure, Field, Input, Row, Skeleton, Stack, Tabs, Textarea, useToast } from '../../ui'
import { noNullIssue } from '../../validators/operateRuntime'
import { confidencePercent, DEFAULT_REVIEW_BELOW_BP, documentErrorMessage, highlightSegments, isLowConfidence, isReviewable, pendingFields, STATUSES } from '../../../shell/documents/documentLogic'
import type { Doc, DocField } from '../../../shell/documents/documentLogic'
import { documentPacksOptions } from './api/documents'
import { runtimeError, runtimeStatus, segment, useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { canWrite } from './api/operate'
import { documentPath, documentsPath } from './api/tools'
import { useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Details, Empty, enumLabel, field, Filter, key, optional, Pager, Panel, Pick, Refresh, RuntimeContents,
  RuntimeState, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { PageSize, ToolsLinks, useListSize } from './components/RuntimeTools'
import { ToolTranslations } from './components/ToolScreen'
import './tools.css'

const PdfTemplates = lazy(() => import('./components/PdfTemplates'))
type Document = Doc & { created_by: string | null }
type Upload = { title: string; kind: string; content: string; idempotency_key?: string }

export default function DocumentsScreen(props: LiveProps) {
  return <ToolTranslations><DocumentsTabs {...props} /></ToolTranslations>
}

function DocumentsTabs(props: LiveProps) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const tab = search.tab === 'pdf' ? 'pdf' : 'queue'
  return <Stack gap={5}>
    <PageHeader title={t(key('documents'))} description={t(key(tab === 'pdf' ? 'pdfLead' : 'documentsLead'))} />
    <Tabs label={t(key('documentViews'))} value={tab} onChange={tab => change({ tab, page: undefined, edit: undefined, status: undefined })}
      items={[
        { id: 'queue', label: t(key('reviewQueue')), content: tab === 'queue' && <RuntimeContents id={props}>
          {session => <Queue session={session} writable={canWrite(props)} />}
        </RuntimeContents> },
        { id: 'pdf', label: t(key('pdfTemplates')), content: tab === 'pdf' && <Suspense fallback={<Skeleton lines={6} />}>
          <PdfTemplates {...props} />
        </Suspense> },
      ]} />
  </Stack>
}

function Queue({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const { size, pickSize } = useListSize(20)
  const [uploading, setUploading] = useState(false)
  const page = search.page ?? 1
  const status = search.status ?? 'needs_review'
  const docs = useRuntimeQuery<Page<Document>>(session, documentsPath, {
    status: status === 'all' ? undefined : status, kind: search.kind, limit: size, offset: (page - 1) * size,
  })
  const lastPage = docs.data ? Math.max(1, Math.ceil(docs.data.total / size)) : page
  useEffect(() => {
    if (page > lastPage) change({ page: lastPage }, true)
  }, [page, lastPage, change])
  const detail = useRuntimeQuery<Document>(session, documentPath(search.edit ?? ''), {}, !!search.edit)
  const settings = useQuery(documentPacksOptions(session.projectId))
  const config = settings.data?.packs?.ai?.documents
  const select = (edit?: string) => change({ edit })
  return <Stack gap={4}>
    <ToolsLinks session={session} sections={['aidocssettings']} />
    <Panel title={'reviewQueue'}>
      <Row><Pick label={t(key('status'))} value={status === 'all' ? '' : status} options={choices(t, STATUSES)}
        onChange={status => change({ status: status || 'all', page: undefined })} />
        <Filter name="kind" max={40} value={search.kind} onChange={kind => change({ kind, page: undefined })} />
        <PageSize value={size} onChange={pickSize} /><Refresh run={docs.refetch} />
        {writable && <Button aria-expanded={uploading} onClick={() => setUploading(!uploading)}>{t(key(uploading ? 'closeUpload' : 'uploadDocument'))}</Button>}
      </Row>
      {docs.isPending || docs.isError ? <RuntimeState error={docs.error} retry={docs.refetch} /> :
        docs.data.items.length ? <Columns label={'reviewQueue'} names={['document', 'kind', 'status']} rows={docs.data.items.map(row => ({
          id: row.id, cells: [
            <Button aria-expanded={search.edit === row.id} onClick={() => select(search.edit === row.id ? undefined : row.id)}>{data(t, row.title)}</Button>,
            data(t, row.kind), <Badge tone={row.status === 'needs_review' ? 'warning' : 'neutral'}>{enumLabel(t, row.status)}</Badge>,
          ],
        }))} /> : <Empty message="noDocuments" action={writable && !uploading ? 'uploadDocument' : undefined}
          onAction={writable && !uploading ? () => setUploading(true) : docs.refetch} />}
      <Pager label={'reviewQueue'} page={page} size={size} total={docs.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {writable && uploading && <UploadDocument session={session} kinds={config?.kinds.map(kind => kind.name) ?? []}
      limit={config?.max_text_chars ?? 200_000} />}
    {search.edit && <Panel title={'documentDetail'}>
      <Row><Button onClick={() => select()}>{t(key('close'))}</Button></Row>
      {detail.isPending || detail.isError ? <RuntimeState error={detail.error} retry={detail.refetch} /> :
        <DocumentDetail key={detail.data.id} session={session} doc={detail.data} writable={writable}
          threshold={config?.review_below_bp ?? DEFAULT_REVIEW_BELOW_BP}
          required={config?.kinds.find(kind => kind.name === detail.data.kind)?.fields.filter(field => field.required).map(field => field.name) ?? []}
          reload={async () => { await Promise.all([docs.refetch(), detail.refetch()]) }} />}
    </Panel>}
  </Stack>
}

function UploadDocument({ session, kinds, limit }: { session: Session; kinds: string[]; limit: number }) {
  const t = useT()
  const write = useRuntimeWrite<Upload, Document>(session, documentsPath)
  const [uploadKey, setUploadKey] = useState(() => crypto.randomUUID())
  const keyInput = useRef<HTMLInputElement>(null)
  return <Panel title={'uploadDocument'}>
    {kinds.length > 0 && <p>{t(key('documentKinds'), { kinds: kinds.join(', ') })}</p>}
    <Form fields={[
      field(t, 'title', { label: 'documentTitle', max: 200, required: true, validate: noNullIssue }),
      field(t, 'kind', { max: 40, required: true, validate: value => noNullIssue(value) ??
        (kinds.length && !kinds.includes(value.trim()) ? { key: key('documentKinds'), values: { kinds: kinds.join(', ') } } : undefined) }),
      field(t, 'content', { label: 'sourceText', area: true, max: limit, required: true, validate: noNullIssue }),
      { ...field(t, 'idempotency_key', { label: 'idempotencyKey', max: 100, validate: noNullIssue }),
        control: attrs => <Input {...attrs} ref={keyInput} defaultValue={uploadKey} maxLength={100} /> },
    ]} key={uploadKey} pending={write.isPending} submitLabel={t(key('uploadDocument'))} serverErrors={serverFields(write.error)}
      actions={<Button disabled={write.isPending} onClick={() => {
        if (keyInput.current) keyInput.current.value = crypto.randomUUID()
      }}>{t(key('newKey'))}</Button>}
      onSubmit={form => write.mutate({ title: text(form, 'title'), kind: text(form, 'kind'),
        content: String(form.get('content') ?? ''), idempotency_key: optional(form, 'idempotency_key') || uploadKey },
      { onSuccess: () => setUploadKey(crypto.randomUUID()) })} />
    <WriteStatus error={write.error} reload={write.reset} replayed={write.data?.replayed} success={write.data ? t(key('documentUploaded')) : undefined} />
  </Panel>
}

function DocumentDetail({ session, doc, writable, threshold, required, reload }: {
  session: Session; doc: Document; writable: boolean; threshold: number; required: string[]; reload: () => Promise<unknown>
}) {
  const t = useT()
  const date = useOperateDate()
  const active = writable && isReviewable(doc.status)
  const evidence = doc.content ? highlightSegments(doc.content, doc.fields) : null
  return <Stack>
    <h3>{data(t, doc.title)}</h3>
    <Details values={[[ 'kind', data(t, doc.kind)], ['status', enumLabel(t, doc.status)], ['reason', data(t, doc.reject_reason)]]} />
    <Disclosure label={t(key('sourceText'))} open>
      {evidence ? <>
        <pre className="v2-tool-source">{evidence.segments.map((part, index) => part.field ?
          <mark key={index}>{data(t, part.text)}</mark> : data(t, part.text))}</pre>
        {evidence.fallbacks.length > 0 && <ul>{evidence.fallbacks.map(anchor => <li key={anchor.field}>
          {t(key(anchor.found ? 'evidenceFound' : 'evidenceMissing'), { field: anchor.field, quote: anchor.quote })}
        </li>)}</ul>}
      </> : <p>{t(key('noSourceText'))}</p>}
    </Disclosure>
    {doc.fields.length > 0 && <Columns label={'extractedFields'} names={['field', 'valueLabel', 'confidence', 'evidence', 'actions']}
      rows={doc.fields.map(entry => ({
        id: entry.name, cells: [
          required.includes(entry.name) ? t(key('requiredFieldName'), { name: entry.name }) : data(t, entry.name),
          <Stack gap={1}><span>{entry.value === null ? t(key('notFound')) : data(t, entry.value)}</span>
            {entry.corrected && <small>{t(key('correctedFrom'), { value: entry.original_value ?? t(key('notFound')) })}</small>}</Stack>,
          <Stack gap={1}><span>{data(t, confidencePercent(entry.confidence_bp))}</span>
            {isLowConfidence(entry, threshold) && <Badge tone="warning">{t(key('lowConfidence'))}</Badge>}</Stack>,
          entry.anchor ? t(key('evidencePage'), { page: entry.anchor.page, quote: entry.anchor.quote }) : t(key('noEvidence')),
          active ? <CorrectField session={session} id={doc.id} entry={entry} reload={reload} /> : null,
        ],
      }))} />}
    {active ? <ReviewActions session={session} doc={doc} reload={reload} /> : !isReviewable(doc.status) && <p>{t(key('documentFinal'))}</p>}
    <Disclosure label={t(key('documentHistory'))}><Details values={[
      ['createdBy', data(t, doc.created_by)], ['created', date(doc.created_at)], ['updated', date(doc.updated_at)],
      ['reviewedBy', data(t, doc.reviewed_by)], ['reviewedAt', date(doc.reviewed_at)], ['callId', data(t, doc.call_id)],
    ]} /></Disclosure>
  </Stack>
}

function ReviewError({ error, reload }: { error: unknown; reload: () => Promise<unknown> }) {
  const t = useT()
  const status = runtimeStatus(error)
  if (!error) return null
  const message = status && status < 500 ? data(t, documentErrorMessage(status, runtimeError(error))) : t(key('writeError'))
  return status === 409 ? <ConflictBanner onReload={() => void reload()}>{message}</ConflictBanner> :
    <Alert tone={status === 403 ? 'warning' : 'danger'}>{message}</Alert>
}

function CorrectField({ session, id, entry, reload }: { session: Session; id: string; entry: DocField; reload: () => Promise<unknown> }) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const write = useRuntimeWrite<{ value: string | null }, Document>(session, `${documentPath(id)}/fields/${segment(entry.name)}/correct`)
  return <Stack>
    {open ? <Form fields={[{ ...field(t, 'value', { max: 10000, value: entry.value ?? '', validate: noNullIssue }),
      label: t(key('correctValue'), { name: entry.name }) }]} pending={write.isPending} submitLabel={t(key('save'))} serverErrors={serverFields(write.error)}
      actions={<Button onClick={() => { write.reset(); setOpen(false) }}>{t(key('cancel'))}</Button>}
      onSubmit={form => {
        const value = String(form.get('value') ?? '')
        write.mutate({ value: value.trim() ? value : null }, {
          onSuccess: () => setOpen(false),
          onError: error => { if ([404, 409].includes(runtimeStatus(error) ?? 0)) void reload() },
        })
      }} /> : <Button aria-label={t(key('correctNamed'), { name: entry.name })} onClick={() => setOpen(true)}>{t(key('correct'))}</Button>}
    <ReviewError error={write.error} reload={reload} />
    {write.isSuccess && !open && <span role="status">{t(key('fieldCorrected'), { name: entry.name })}</span>}
  </Stack>
}

function ReviewActions({ session, doc, reload }: { session: Session; doc: Document; reload: () => Promise<unknown> }) {
  const t = useT()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const approve = useRuntimeWrite<{ acknowledge: string[] } | undefined, Document>(session, `${documentPath(doc.id)}/approve`)
  const reject = useRuntimeWrite<{ reason?: string }, Document>(session, `${documentPath(doc.id)}/reject`)
  const flagged = pendingFields(runtimeError(approve.error))
  const pending = approve.isPending || reject.isPending
  const refreshOnError = (error: unknown) => {
    if ([404, 409].includes(runtimeStatus(error) ?? 0)) void reload()
  }
  const submitApproval = (acknowledge?: string[]) => {
    reject.reset()
    void approve.mutateAsync(acknowledge ? { acknowledge } : undefined)
      .then(() => toast({ title: t(key('documentApproved')), tone: 'success' }), refreshOnError)
  }
  return <Stack>
    <Row>
      <Button variant="primary" disabled={pending} onClick={() => submitApproval()}>{t(key('approve'))}</Button>
      <ConfirmDestructive trigger={<Button variant="danger" disabled={pending}>{t(key('reject'))}</Button>}
        title={t(key('rejectDocument'))} description={t(key('rejectDocumentHelp'))} action={t(key('rejectDocument'))}
        pending={reject.isPending} disabled={reason.includes('\0')} onConfirm={async () => {
          approve.reset()
          try {
            await reject.mutateAsync({ reason: reason.trim() || undefined })
            toast({ title: t(key('documentRejected')), tone: 'success' })
          } catch (error) {
            refreshOnError(error)
            throw error
          }
        }}>
        <Field label={t(key('optionalReason'))} error={reason.includes('\0') ? t(key('nullCharacter')) : undefined}>
          {attrs => <Textarea {...attrs} value={reason} maxLength={500} onChange={event => setReason(event.target.value)} />}
        </Field>
      </ConfirmDestructive>
    </Row>
    <ReviewError error={approve.error || reject.error} reload={reload} />
    {flagged.length > 0 && <Alert tone="warning" action={<Button disabled={pending} onClick={() => submitApproval(flagged)}>
      {t(key('ackApprove'))}</Button>}>{t(key('flaggedFields'), { fields: flagged.join(', ') })}</Alert>}
  </Stack>
}
