import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import type { MigrationPlanRequest } from '../../../api/types'
import { clearBaseline, diffSpecs, loadBaseline, saveBaseline } from '../../../shell/specdiff/diffLogic'
import { useT } from '../../i18n'
import { Form, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, CodeBlock, EmptyState, Field, Grid, Input, Pagination, Row, Select, Stack, Table, Textarea } from '../../ui'
import type { FieldAttributes } from '../../ui'
import { buildLimits, defaultLimits, jsonObject, validators } from '../../validators'
import { buildQueries, generationOptions, planMigration, versionPageSize } from './api/build'
import type { Spec } from './api/build'
import { BuildFailure, BuildLoad, BuildPage, Pick, useBuildDate, useVersionLabel, WriteAccess } from './components/shared'
import type { BuildScreenProps } from './components/shared'
import { route, useBuildRoute } from './routes'

const maxFileBytes = 2 * 1024 * 1024
const redactKey = /secret|password|token|credential|private_key|api_key/i
function safeValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safeValue)
  if (value === null || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) =>
    [key, redactKey.test(key) ? null : safeValue(item)]))
}

export default function SpecDiffScreen({ access }: BuildScreenProps) {
  const { projectId } = useBuildRoute()
  return <BuildPage screen="specdiff" desktop><SpecDiff key={projectId} access={access} /></BuildPage>
}

function SpecDiff({ access }: BuildScreenProps) {
  const t = useT()
  const label = useVersionLabel()
  const date = useBuildDate()
  const { projectId, search, update } = useBuildRoute()
  const page = search.page ?? 1
  const current = useQuery(buildQueries.spec(projectId))
  const versions = useQuery(buildQueries.ops(projectId, page))
  const from = useQuery(buildQueries.at(projectId, search.base))
  const to = useQuery(buildQueries.at(projectId, search.compare))
  const [stored, setStored] = useState(() => loadBaseline(localStorage, projectId))
  const [imported, setImported] = useState<{ spec: Spec; source: 'paste' | 'upload' }>()
  const baseline = imported ?? stored
  const [error, setError] = useState<string>()
  const [copied, setCopied] = useState(false)

  const before = search.base === undefined ? baseline?.spec : from.data
  const after = search.compare === undefined ? current.data : to.data
  const diff = before && after ? diffSpecs(safeValue(before) as Spec, safeValue(after) as Spec) : undefined
  const selected = [...new Set([0, ...versions.data?.items.map(op => op.seq) ?? [], ...[search.base, search.compare].filter(seq => seq !== undefined)])]
  const comparisons = selected.map(seq => {
    const op = versions.data?.items.find(item => item.seq === seq)
    return { value: String(seq), label: seq === 0 ? t('buildSpec.timeline.start') : op ? label(op) : t('buildSpec.versionNumber', { version: seq }) }
  })

  function store(spec: Spec) {
    const saved = saveBaseline(localStorage, projectId, safeValue(spec) as Spec)
    if (!saved) { setError(t('buildSpec.specdiff.storage')); return }
    setStored(saved)
    setImported(undefined)
    update({ base: undefined })
    setError(undefined)
  }

  function applyText(value: string, source: 'paste' | 'upload') {
    const invalid = jsonObject(value)
    if (invalid) { setError(t(invalid.key, invalid.values)); return }
    setImported({ spec: safeValue(JSON.parse(value)) as Spec, source })
    update({ base: undefined })
    setError(undefined)
  }

  async function upload(file?: File) {
    if (!file) return
    if (file.size > maxFileBytes) { setError(t('buildSpec.specdiff.fileSize')); return }
    try { applyText(await file.text(), 'upload') } catch { setError(t('buildSpec.specdiff.fileRead')) }
  }

  function clear() {
    clearBaseline(localStorage, projectId)
    setStored(null)
    setImported(undefined)
    update({ base: undefined })
    setError(undefined)
  }

  return <BuildLoad reads={[current, versions]}>
    <Row>
      <Button onClick={() => void current.refetch()} disabled={current.isFetching}>{t('buildSpec.specdiff.reload')}</Button>
      <Button variant="primary" onClick={() => current.data && store(current.data)}>{t('buildSpec.specdiff.save')}</Button>
      {(baseline || search.base !== undefined) && <Button onClick={clear}>{t('buildSpec.specdiff.clear')}</Button>}
    </Row>
    <SettingsSection title={t('buildSpec.specdiff.baseline')}>
      {search.base === undefined && imported && <p className="v2-muted">{t('buildSpec.specdiff.' + imported.source)}</p>}
      {search.base === undefined && !imported && stored && <p className="v2-muted">{t('buildSpec.specdiff.savedAt', { date: date(stored.savedAt) })}</p>}
      <Grid>
        <Pick label={t('buildSpec.specdiff.from')} value={search.base === undefined ? 'snapshot' : String(search.base)}
          options={[{ value: 'snapshot', label: t(imported ? 'buildSpec.specdiff.' + imported.source : baseline ? 'buildSpec.specdiff.browser' : 'buildSpec.specdiff.choose') }, ...comparisons]}
          onChange={value => { setCopied(false); update({ base: value === 'snapshot' ? undefined : Number(value) }) }} />
        <Pick label={t('buildSpec.specdiff.to')} value={search.compare === undefined ? 'current' : String(search.compare)}
          options={[{ value: 'current', label: t('buildSpec.specdiff.current') }, ...comparisons]}
          onChange={value => { setCopied(false); update({ compare: value === 'current' ? undefined : Number(value) }) }} />
      </Grid>
      <Row>
        {(search.base !== undefined || search.compare !== undefined) && <Button onClick={async () => {
          try { await navigator.clipboard.writeText(location.href); setCopied(true); setError(undefined) }
          catch { setError(t('buildSpec.specdiff.clipboard')) }
        }}>{t(copied ? 'buildSpec.specdiff.copied' : 'buildSpec.specdiff.copy')}</Button>}
        <Pagination label={t('buildSpec.timeline.versions')} page={page} pages={Math.ceil((versions.data?.total ?? 0) / versionPageSize)}
          onChange={page => update({ page: page > 1 ? page : undefined })} />
      </Row>
      <Form fields={[{ name: 'json', label: t('buildSpec.specdiff.json'), validate: [validators.length(defaultLimits.longText), jsonObject],
        control: attrs => <Textarea {...attrs} maxLength={defaultLimits.longText} /> }]}
        submitLabel={t('buildSpec.specdiff.use')} onSubmit={data => applyText(String(data.get('json') ?? ''), 'paste')} />
      <Field label={t('buildSpec.specdiff.upload')}>{attrs => <Input {...attrs} type="file" accept=".json,application/json"
        onChange={event => { const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; void upload(file) }} />}</Field>
      {error && <Alert tone="danger">{error}</Alert>}
    </SettingsSection>
    <BuildLoad reads={[...(search.base === undefined ? [] : [from]), ...(search.compare === undefined ? [] : [to])]}>
      {!diff && <EmptyState title={t('buildSpec.specdiff.empty')} description={t('buildSpec.specdiff.emptyDetail')}
        action={<Button onClick={() => current.data && store(current.data)}>{t('buildSpec.specdiff.save')}</Button>} />}
      {diff && (diff.total ? <Stack data-testid="specdiff-result">
        <p>{t('buildSpec.specdiff.differences', { count: diff.total })}</p>
        {diff.truncated && <Alert tone="warning">{t('buildSpec.specdiff.truncated')}</Alert>}
        {diff.sections.map(section => <SettingsSection title={t('buildSpec.diffSections.' + section.id)} key={section.id}>
          {section.items.map(item => <Stack key={item.key} gap={1}>
            <Row><Badge tone={item.kind === 'removed' ? 'danger' : item.kind === 'added' ? 'success' : 'warning'}>{t('buildSpec.diffKind.' + item.kind)}</Badge><code>{item.key}</code></Row>
            {item.changes.length > 0 && <ul>{item.changes.map((change, index) => <li key={index}>
              {change.redacted ? t('buildSpec.specdiff.redacted', { label: change.label })
                : t('buildSpec.specdiff.change', { label: change.label, before: change.before ?? t('buildSpec.none'), after: change.after ?? t('buildSpec.none') })}
            </li>)}</ul>}
          </Stack>)}
        </SettingsSection>)}
        <SectionLinkToAccess projectId={projectId} />
      </Stack> : <EmptyState title={t('buildSpec.specdiff.same')} description={t('buildSpec.specdiff.sameDetail')} />)}
    </BuildLoad>
    {from.isSuccess && search.base !== undefined && <Row><Button asChild>
      <Link to={route} params={{ projectId, section: 'timeline' }} search={{ version: search.base }}>{t('buildSpec.specdiff.restoreLink')}</Link>
    </Button></Row>}
    <MigrationPlan projectId={projectId} access={access} />
  </BuildLoad>
}

function SectionLinkToAccess({ projectId }: { projectId: string }) {
  const t = useT()
  return <Row><Button asChild><Link to={route} params={{ projectId, section: 'permissions' }}>{t('buildSpec.specdiff.access')}</Link></Button></Row>
}

function MigrationPlan({ projectId, access }: { projectId: string } & BuildScreenProps) {
  const t = useT()
  const date = useBuildDate()
  const generations = useQuery({ ...generationOptions(projectId), enabled: access.writable })
  const plan = useMutation({ mutationFn: (input: Parameters<typeof planMigration>[1]) => planMigration(projectId, input) })
  const result = plan.data
  const steps = result?.plan.steps ?? []
  const columns = ['step', 'where', 'safety', 'why'].map(id => ({ id, label: t('buildSpec.migration.' + id) }))
  const disabled = !access.writable || plan.isPending

  function submit(data: FormData) {
    const generation = String(data.get('generation') ?? '')
    const entity = String(data.get('entity') ?? '').trim()
    const from = String(data.get('from') ?? '').trim()
    const to = String(data.get('to') ?? '').trim()
    const kind = String(data.get('kind') ?? '')
    const body: MigrationPlanRequest = {
      ...(generation && generation !== 'latest' ? { against_generation_id: generation } : {}),
      ...(from && to ? { renames: [{ kind, entity, from, to }] } : {}),
    }
    plan.mutate({ body, accept: false })
  }

  return <SettingsSection title={t('buildSpec.migration.title')} description={t('buildSpec.migration.intro')}>
    <WriteAccess access={access} />
    {generations.isError && <Alert action={<Button onClick={() => void generations.refetch()}>{t('common.retry')}</Button>}>{t('buildSpec.migration.generationError')}</Alert>}
    <Form pending={plan.isPending} readOnly={disabled} submitLabel={t('buildSpec.migration.run')} onSubmit={submit} fields={[
      { name: 'generation', label: t('buildSpec.migration.baseline'), control: ({ name, disabled, ...attrs }) =>
        <SelectGeneration name={name} disabled={disabled} attrs={attrs} items={generations.data?.items.map(item => ({ value: item.id, label: date(item.created_at) })) ?? []} /> },
    ]}>
      <details>
        <summary className="v2-status-disclosure">{t('buildSpec.migration.rename')}</summary>
        <Grid>
          <Field label={t('buildSpec.migration.kind')}>{attrs => <MigrationKind attrs={attrs} disabled={disabled} />}</Field>
          {['entity', 'from', 'to'].map(id => <Field key={id} label={t('buildSpec.migration.' + id)}>{attrs =>
            <Input {...attrs} name={id} maxLength={buildLimits.identifier} disabled={disabled} />}</Field>)}
        </Grid>
      </details>
    </Form>
    <BuildFailure error={plan.error} reload={() => plan.reset()} />
    {result?.old_snapshot_unusable && <Alert tone="warning" action={<Button disabled={disabled}
      onClick={() => plan.mutate({ body: plan.variables?.body ?? {}, accept: true })}>{t('buildSpec.migration.emptyBaseline')}</Button>}>{t('buildSpec.migration.unreadable')}</Alert>}
    {result?.first_generation && !result.old_snapshot_unusable && <Alert>{t('buildSpec.migration.first')}</Alert>}
    {result && !result.old_snapshot_unusable && !steps.length && <Alert tone="success">{t('buildSpec.migration.noChanges')}</Alert>}
    {result?.allow_destructive_required && <Alert tone="warning">{t('buildSpec.migration.destructive')}</Alert>}
    {result?.plan.requires_backfill && <Alert tone="warning">{t('buildSpec.migration.backfill')}</Alert>}
    {steps.length > 0 && <Table label={t('buildSpec.migration.title')} columns={columns} rows={steps.map(step => ({
      id: String(step.seq), cells: [step.kind.replaceAll('_', ' '), t('buildSpec.migration.location', {
        phase: step.phase, entity: step.entity, table: step.table, field: step.field ?? t('buildSpec.none'),
      }), <Badge key="safety" tone={step.safety === 'safe' ? 'success' : 'warning'}>{t('buildSpec.migration.safety_' + step.safety)}</Badge>,
      <Stack key="reason" gap={1}><p>{step.reason}</p>{step.suggested_action && <p>{step.suggested_action}</p>}
        {step.note && <p>{step.note}</p>}{step.backfill_strategy && <p>{step.backfill_strategy}</p>}{step.sql_hint && <CodeBlock code={step.sql_hint} />}</Stack>],
    }))} />}
    {result?.plan.ignored_sections.length ? <p>{t('buildSpec.migration.ignored', { sections: result.plan.ignored_sections.join(', ') })}</p> : null}
    {result?.text && <details><summary className="v2-status-disclosure">{t('buildSpec.migration.text')}</summary><CodeBlock code={result.text} /></details>}
  </SettingsSection>
}

function SelectGeneration({ name, disabled, attrs, items }: { name: string; disabled?: boolean; attrs: FieldAttributes; items: { value: string; label: string }[] }) {
  const t = useT()
  return <Select name={name} disabled={disabled} triggerProps={attrs} defaultValue="latest"
    options={[{ value: 'latest', label: t('buildSpec.migration.latest') }, ...items]} />
}

function MigrationKind({ attrs, disabled }: { attrs: FieldAttributes; disabled?: boolean }) {
  const t = useT()
  return <Select name="kind" disabled={disabled} triggerProps={attrs} defaultValue="entity"
    options={['entity', 'field'].map(value => ({ value, label: t('buildSpec.migration.' + value) }))} />
}
