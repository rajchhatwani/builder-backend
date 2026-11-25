import { useReducer, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { ConfirmDestructive, ConflictBanner, Form } from '../../../patterns'
import { Alert, Button, Checkbox, DesktopOnlyCard, Disclosure, Field, Grid, Input, Row, Stack } from '../../../ui'
import { jsonObjectIssue, pdfComputeIssue, pdfIdIssue, pdfPreviewIssue, pdfRateIssue, readJsonObject } from '../../../validators/operateRuntime'
import { documentsOptions, libraryOptions, documentIssuesOptions, documentSpecOptions, useSaveDocuments, usePdfPreview } from '../api/documents'
import type { DocumentTemplate, LibraryTemplate } from '../api/documents'
import type { LiveProps } from '../api/live'
import { canWrite, errorInfo } from '../api/operate'
import { pdfDraft } from '../state/pdfDraft'
import { RoleNotice, SectionLink, useOperateDate, useOperateSearch } from './Common'
import { Columns, data, Empty, field, key, Panel, Pick, RuntimeState, serverFields, text, WriteStatus } from './Runtime'
import { JsonDetails } from './RuntimeTools'
import { PdfBlocks } from './PdfBlocks'
import { usePdfUrl } from './usePdfUrl'
import { GeneratedPdfs } from './GeneratedPdfs'

export default function PdfTemplates(props: LiveProps) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const openLibrary = useRef<HTMLDetailsElement>(null)
  const [draft, dispatch] = useReducer(pdfDraft, null)
  const settings = useQuery(documentsOptions(props.projectId))
  const library = useQuery(libraryOptions(props.projectId))
  const spec = useQuery(documentSpecOptions(props.projectId))
  const issues = useQuery(documentIssuesOptions(props.projectId))
  const save = useSaveDocuments(props.projectId)
  const writable = canWrite(props)
  const base = settings.data
  const form = draft ?? base
  const index = search.edit && /^\d+$/.test(search.edit) ? Number(search.edit) : -1
  const edit = (i?: number) => change({ edit: i === undefined ? undefined : String(i) })
  const reload = async () => {
    const reply = await settings.refetch()
    if (reply.isSuccess) {
      dispatch({ type: 'reset' })
      save.reset()
    }
    void issues.refetch()
  }
  if (settings.isPending || settings.isError || !form || !base) return <RuntimeState error={settings.error} retry={reload} />
  const roles = spec.data?.auth?.roles?.map(role => role.name) ?? []
  const entities = spec.data?.entities?.map(entity => entity.name) ?? []
  const current = form.templates[index]
  const problems = issues.data?.issues ?? []
  const conflict = errorInfo(save.error)?.status === 409
  const busy = save.isPending
  const templateInvalid = form.templates.some(item => pdfIdIssue(item.id) || pdfComputeIssue(item.compute ?? ''))
  const duplicate = new Set(form.templates.map(item => item.id)).size !== form.templates.length
  const submit = () => save.mutate({ enabled: form.enabled, rate_limit: form.rate_limit, templates: form.templates, expected_version: form.version },
    { onSuccess: () => dispatch({ type: 'reset' }) })
  return <Stack gap={4}>
    <RoleNotice {...props} />
    {conflict ? <ConflictBanner onReload={() => void reload()}>{t(key('pdfConflict'))}</ConflictBanner> :
      <WriteStatus error={save.error} reload={reload} success={save.isSuccess ? t(key('documentsSaved')) : undefined} />}
    {issues.isError && <RuntimeState error={issues.error} retry={issues.refetch} />}
    {problems.length > 0 && <Panel title={'pdfIssues'}><Stack>
      {problems.map((problem, i) => {
        const item = /^documents\.templates\[(\d+)\]/.exec(problem.path)
        return <Row key={i}><span>{t(key('pdfIssue'), { path: problem.path, message: problem.message })}</span>
          {item && form.templates[Number(item[1])] && <Button onClick={() => edit(Number(item[1]))}>{t(key('openTemplate'))}</Button>}
        </Row>
      })}
    </Stack></Panel>}
    <div className="v2-phone-only"><DesktopOnlyCard /></div>
    <Panel title={'pdfGeneration'}>
      {form.enabled && spec.isSuccess && (!spec.data.auth || spec.data.auth.enabled === false) && <Alert tone="warning"
        action={<SectionLink id={props.projectId} section="auth" label={t(key('authSettings'))} />}>{t(key('pdfNeedsAuth'))}</Alert>}
      <div className="v2-phone-hidden"><Stack>
        {form.enabled && writable ? <Row><ConfirmDestructive trigger={<Button variant="danger" disabled={busy}>{t(key('disablePdf'))}</Button>}
          title={t(key('disablePdf'))} description={t(key('disablePdfHelp'))} action={t(key('disablePdf'))}
          onConfirm={() => dispatch({ type: 'settings', patch: { enabled: false }, base })} /></Row> :
          <Checkbox label={t(key('enablePdf'))} checked={form.enabled} disabled={!writable || busy}
            onChange={event => dispatch({ type: 'settings', patch: { enabled: event.target.checked }, base })} />}
        <EditText label={'rateLimit'} value={form.rate_limit} max={20} disabled={!writable || busy}
          validate={pdfRateIssue} onChange={rate_limit => dispatch({ type: 'settings', patch: { rate_limit }, base })} />
      </Stack></div>
      <p>{base.updated_at ? t(key('pdfVersion'), { version: base.version, date: date(base.updated_at) }) : t(key('pdfNeverSaved'))}</p>
    </Panel>
    <Panel title={'yourTemplates'}>
      {form.templates.length ? <Columns label={'yourTemplates'} names={['template', 'route', 'roles', 'actions']}
        rows={form.templates.map((item, i) => ({
          id: String(i), cells: [data(t, item.title || item.id), <code>{t(key(item.entity ? 'pdfRecordRoute' : 'pdfRenderRoute'), { id: item.id })}</code>,
            item.roles.length ? data(t, item.roles.join(', ')) : t(key('nobodyRenders')), <Row>
              <Button aria-expanded={i === index} onClick={() => edit(i === index ? undefined : i)}>{t(key(i === index ? 'close' : 'openTemplate'))}</Button>
              {writable && <div className="v2-phone-hidden"><ConfirmDestructive trigger={<Button variant="danger" disabled={busy}>{t(key('remove'))}</Button>}
                title={t(key('removeTemplate'), { name: item.title })} description={t(key('removeTemplateHelp'))} action={t(key('remove'))}
                onConfirm={() => { dispatch({ type: 'remove', index: i, base }); edit() }} /></div>}
            </Row>],
        }))} /> : <Empty message="noTemplates" action="openLibrary" onAction={() => {
          if (openLibrary.current) openLibrary.current.open = true
          openLibrary.current?.querySelector('summary')?.focus()
        }} />}
    </Panel>
    {current && <Panel title={'templateEditor'}>
      <div className="v2-phone-hidden">
        <TemplateEditor key={index} item={current} roles={roles} entities={entities} disabled={!writable || busy}
          change={patch => dispatch({ type: 'template', index, patch, base })} />
      </div>
      <PreviewPdf projectId={props.projectId} item={current} samples={library.data ?? []} />
    </Panel>}
    {writable && <div className="v2-phone-hidden"><Row>
      <span role="status">{t(key(draft ? 'unsaved' : 'saved'))}</span>
      <Button disabled={!draft || busy} onClick={() => void reload()}>{t(key('discard'))}</Button>
      <Button variant="primary" disabled={!draft || busy || conflict || duplicate || templateInvalid || !!pdfRateIssue(form.rate_limit)}
        onClick={submit}>{t(key('save'))}</Button>
      {duplicate && <Alert tone="danger">{t(key('pdfDuplicate'))}</Alert>}
      {!!Object.keys(serverFields(save.error)).length && <Alert tone="danger">{t(key('pdfInvalidSettings'))}</Alert>}
    </Row></div>}
    <Disclosure ref={openLibrary} label={t(key('pdfLibrary'))} open={form.templates.length === 0 || undefined}>
      {library.isPending || library.isError ? <RuntimeState error={library.error} retry={library.refetch} /> :
        library.data.length ? <Grid>{library.data.map(item => <Panel key={item.id} title={'libraryTemplate'}>
          <h3>{data(t, item.title)}</h3><p>{data(t, item.industries.join(', '))}</p><p>{data(t, item.why)}</p>
          {item.compute && <p>{t(key('libraryCompute'), { name: item.compute })}</p>}
          <JsonDetails label={'sampleData'} value={item.sample} />
          {writable && <div className="v2-phone-hidden"><Row><Button disabled={busy || form.templates.length >= 30}
            aria-label={t(key('addTemplateNamed'), { name: item.title })} onClick={() => {
              dispatch({ type: 'add', item, roles, base })
              edit(form.templates.length)
            }}>{t(key('addTemplate'))}</Button></Row></div>}
        </Panel>)}</Grid> : <Empty message="noLibrary" onAction={library.refetch} />}
    </Disclosure>
    {spec.isError && <RuntimeState error={spec.error} retry={spec.refetch} />}
    <GeneratedPdfs {...props} />
  </Stack>
}

export function EditText({ label, value, onChange, disabled, max, validate }: {
  label: string; value: string; onChange: (value: string) => void; disabled: boolean; max?: number
  validate?: (value: string) => ReturnType<typeof pdfIdIssue>
}) {
  const t = useT()
  const [touched, touch] = useState(false)
  const issue = touched ? validate?.(value) : undefined
  return <Field label={t(key(label))} error={issue && t(issue.key, issue.values)}>
    {attrs => <Input {...attrs} value={value} maxLength={max} disabled={disabled} onBlur={() => touch(true)}
      onChange={event => onChange(event.target.value)} />}
  </Field>
}

function TemplateEditor({ item, roles, entities, change, disabled }: {
  item: DocumentTemplate; roles: string[]; entities: string[]; change: (patch: Partial<DocumentTemplate>) => void; disabled: boolean
}) {
  const t = useT()
  const template = (patch: Partial<DocumentTemplate['template']>) => change({ template: { ...item.template, ...patch } })
  const page = item.template.page ?? {}
  const select = (label: string, value: string, options: string[], update: (value: string) => void, symbolic = true) =>
    disabled ? <p>{t(key('labelValue'), { label: t(key(label)), value: symbolic ? t(key(value)) : value })}</p> :
      <Pick label={t(key(label))} value={value} options={options.map(value => ({
        value, label: symbolic ? t(key(value)) : value === '_request' ? t(key('requestData')) : data(t, value),
      }))} onChange={update} />
  return <Stack>
    <Grid>
      <EditText label={'documentTitle'} value={item.title} disabled={disabled} max={120}
        onChange={title => change({ title, template: { ...item.template, title } })} />
      <EditText label={'urlName'} value={item.id} disabled={disabled} max={40} validate={pdfIdIssue} onChange={id => change({ id })} />
      {select('dataSource', item.entity ?? '_request', ['_request', ...new Set([...entities, ...(item.entity ? [item.entity] : [])])],
        entity => change({ entity: entity === '_request' ? null : entity, ...(entity === '_request' ? {} : { compute: null }) }), false)}
      {!item.entity && <EditText label={'computeTotals'} value={item.compute ?? ''} max={60} disabled={disabled} validate={pdfComputeIssue}
        onChange={compute => change({ compute: compute || null })} />}
      {select('pageSize', page.size ?? 'A4', ['A4', 'Letter'], size => template({ page: { ...page, size } }))}
      {select('orientation', page.orientation ?? 'portrait', ['portrait', 'landscape'], orientation => template({ page: { ...page, orientation } }))}
      <EditText label={'pdfHeader'} value={item.template.header ?? ''} disabled={disabled} onChange={header => template({ header })} />
      <EditText label={'pdfFooter'} value={item.template.footer ?? ''} disabled={disabled} onChange={footer => template({ footer })} />
    </Grid>
    <fieldset><legend>{t(key('renderRoles'))}</legend><Stack>
      <p>{t(key('rolesHint'))}</p>
      {[...new Set([...roles, ...item.roles])].map(role => <Checkbox key={role} disabled={disabled || (item.roles.length >= 50 && !item.roles.includes(role))}
        label={data(t, role)} checked={item.roles.includes(role)} onChange={event =>
          change({ roles: event.target.checked ? [...item.roles, role] : item.roles.filter(value => value !== role) })} />)}
    </Stack></fieldset>
    <PdfBlocks blocks={item.template.blocks ?? []} disabled={disabled} onChange={blocks => template({ blocks })} />
  </Stack>
}

function PreviewPdf({ projectId, item, samples }: { projectId: string; item: DocumentTemplate; samples: LibraryTemplate[] }) {
  const t = useT()
  const preview = usePdfPreview(projectId)
  const url = usePdfUrl(preview.data)
  const sample = samples.find(sample => sample.id === item.kind)
  return <Disclosure label={t(key('pdfPreview'))}><Stack>
    <Form key={sample?.id} fields={[field(t, 'sampleData', { area: true, value: JSON.stringify(sample?.sample ?? {}, null, 2),
      validate: value => jsonObjectIssue(value) ?? pdfPreviewIssue(item.template.blocks ?? [], readJsonObject(value) ?? {}) })]}
      pending={preview.isPending} submitLabel={t(key('renderPreview'))} onSubmit={form => {
        const values = readJsonObject(text(form, 'sampleData'))
        if (values) preview.mutate({ template: item.template, data: values, compute: item.compute })
      }} />
    <WriteStatus error={preview.error} reload={preview.reset} />
    {url && <Stack>
      <iframe className="v2-tool-pdf" title={t(key('pdfPreview'))} src={url} />
      <Button asChild><a href={url} download="preview.pdf">{t(key('downloadPdf'))}</a></Button>
    </Stack>}
  </Stack></Disclosure>
}
