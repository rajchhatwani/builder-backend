import { useQuery } from '@tanstack/react-query'
import { useBlocker, useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useReducer, useRef, useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, ConflictBanner, PageHeader, ReadOnlyNote, SettingsSection } from '../../patterns'
import { documentAccept, guidedLimits, validators } from '../../validators'
import { Alert, Badge, Button, Card, Dialog, EmptyState, Field, Grid, Input, Pagination, Row, Select, Skeleton, Stack, Table, Textarea, useToast } from '../../ui'
import { errorCode, errorStatus, fieldMessage, mapOptions, questionConflictTexts, serverMessage, useGuidedAccess, useGuidedWorkspaces, useMapWrite, useStartRun } from './api/guided'
import { GuidedLoadError, useGuidedError } from './components/GuidedFeedback'
import { RequirementDetails, RequirementQuestionCard } from './components/RequirementDetails'
import { emptyDraft, intakeReducer } from './state/intake'
import './guided.css'

const pageSize = 25
const groups = ['actor', 'entity', 'workflow', 'rule', 'integration', 'compliance', 'nonfunctional', 'out_of_scope']

export default function IntakeScreen() {
  const t = useT()
  const { projectId } = useParams({ from: '/projects/$projectId/$section' })
  const search = useSearch({ from: '/projects/$projectId/$section' })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const map = useQuery(mapOptions(projectId))
  const access = useGuidedAccess(projectId)
  const write = useMapWrite(projectId)
  const startRun = useStartRun(projectId)
  const toast = useToast()
  const describeError = useGuidedError()
  const [draft, dispatch] = useReducer(intakeReducer, emptyDraft)
  const [promptTouched, setPromptTouched] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const prompt = useRef<HTMLTextAreaElement>(null)
  const canEdit = access.role === 'owner' || access.role === 'editor'
  const busy = write.isPending || startRun.isPending
  const submitting = write.isPending && write.variables?.kind === 'intake'
  const dirty = Boolean(draft.prompt.trim() || draft.files.length)
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => dirty && current.pathname !== next.pathname,
    enableBeforeUnload: dirty,
    withResolver: true,
  })

  const data = map.data
  const items = data?.items ?? []
  const questions = data?.questions ?? []
  const coverage = data?.coverage
  const inScope = coverage ? coverage.total - coverage.out_of_scope : items.filter(item => item.status !== 'out_of_scope').length
  const phases = data?.phases ?? []
  const phase = phases.find(item => item.number === search.phase) ?? phases[0]
  const workspaces = useGuidedWorkspaces(projectId, canEdit && inScope > 0)
  const availableWorkspaces = workspaces.data?.filter(workspace => workspace.state === 'active' || workspace.state === 'rolled_back') ?? []
  const workspace = availableWorkspaces.find(item => item.id === search.workspace)
  const openQuestions = questions.filter(question => question.state === 'open')
  const intakeError = write.variables?.kind === 'intake' ? write.error : null
  const promptIssue = validators.length(guidedLimits.prompt)(draft.prompt)
  const promptMessage = (promptTouched && promptIssue ? t(promptIssue.key, { ...promptIssue.values, field: t('intake.prompt') }) : undefined)
    ?? (fieldMessage(intakeError, 'prompt')
      || (errorCode(intakeError) === 'prompt_too_large' ? serverMessage(intakeError) : undefined))
  const intakeCode = errorCode(intakeError)
  const documentMessage = fieldMessage(intakeError, 'files') || (intakeCode && (
    intakeCode.startsWith('file_') || ['too_many_chunks', 'too_many_files', 'files_too_large', 'body_too_large'].includes(intakeCode)
  ) ? describeError(intakeError) : undefined)
  const startDisabled = !inScope || !access.verified || busy || Boolean(search.workspace && !workspace)
  const workspaceMissing = !!search.workspace && workspaces.isSuccess && !workspace
  const conflict = errorStatus(startRun.error) === 409 ? startRun.error
    : errorStatus(write.error) === 409 ? write.error : null
  const conflictQuestions = errorCode(startRun.error) === 'questions_open' ? questionConflictTexts(startRun.error) : []
  const kinds = [...groups, ...[...new Set(items.map(item => item.kind))].filter(kind => !groups.includes(kind)).sort()]
  const pages = Math.ceil(items.length / pageSize)
  const page = Math.min(search.page ?? 1, Math.max(pages, 1))
  const pageItems = kinds.flatMap(kind => items.filter(item => item.kind === kind)).slice((page - 1) * pageSize, page * pageSize)

  function reload() {
    write.reset()
    startRun.reset()
    void map.refetch()
  }

  async function start(accept: boolean) {
    try {
      const run = await startRun.mutateAsync({ accept_assumptions: accept, phase: phase?.number ?? 1, workspace_id: workspace?.id ?? null })
      setConfirm(false)
      await navigate({ to: '/projects/$projectId/$section', params: { projectId, section: 'build' }, search: { run: run.id }, ignoreBlocker: true })
    } catch {
      setConfirm(false)
    }
  }

  return <Stack gap={5} data-testid="intake-page">
    <PageHeader title={t('intake.title')} description={t('intake.intro')} />
    {map.isPending ? <Grid gap={4}>
      <Card><Skeleton lines={8} label={t('intake.loading')} /></Card><Card><Skeleton lines={6} /></Card>
    </Grid> : map.isError && !data ? <GuidedLoadError error={map.error} retry={reload} label={t('intake.loadError')} /> : <>
      {access.failed && <GuidedLoadError error={access.account.error ?? access.members.error} retry={access.retry} label={t('guided.accessError')} />}
      {!access.pending && !access.failed && !canEdit && <ReadOnlyNote />}
      {canEdit && !access.verified && <ReadOnlyNote>{t('guided.verify')}</ReadOnlyNote>}
      {conflict && <ConflictBanner onReload={reload}>{describeError(conflict)}</ConflictBanner>}
      {map.isError && <GuidedLoadError error={map.error} retry={reload} label={t('intake.loadError')} />}
      <Grid gap={4} className="v2-guided-columns">
        <Stack gap={4}>
          <SettingsSection title={t('intake.request')}>
            <form onSubmit={event => {
              event.preventDefault()
              setPromptTouched(true)
              if (promptIssue) { prompt.current?.focus(); return }
              if (!dirty || busy || !canEdit || !access.verified) return
              void write.mutateAsync({ kind: 'intake', prompt: draft.prompt.trim(), files: draft.files }).then(() => {
                dispatch({ type: 'clear' }); setPromptTouched(false)
                toast({ title: t('intake.updated'), tone: 'success' })
              }, error => { if (fieldMessage(error, 'prompt')) prompt.current?.focus() })
            }}>
              <Stack gap={3} aria-busy={submitting}>
                <Field label={t('intake.prompt')} error={promptMessage && t('common.serverText', { text: promptMessage })}>{attrs =>
                  <Textarea {...attrs} ref={prompt} rows={8} maxLength={guidedLimits.prompt} value={draft.prompt}
                    placeholder={t('intake.placeholder')} disabled={!canEdit || !access.verified || busy}
                    onBlur={() => setPromptTouched(true)} onChange={event => {
                      dispatch({ type: 'prompt', value: event.target.value })
                      if (intakeError) write.reset()
                    }} />}
                </Field>
                {canEdit && <Field label={t('intake.documents')} hint={t('intake.documentLimits')} error={documentMessage}>{attrs =>
                  <Input {...attrs} type="file" multiple accept={documentAccept} disabled={!access.verified || busy} onChange={event => {
                    dispatch({ type: 'pick', files: Array.from(event.target.files ?? []) })
                    event.target.value = ''
                    if (intakeError) write.reset()
                  }} />}
                </Field>}
                <Stack data-testid="intake-files" gap={2}>
                  {draft.files.map((file, index) => <Row key={`${file.name}:${index}`} className="v2-spread">
                    <span>{t('common.serverText', { text: file.name })}</span>
                    <Button disabled={busy} aria-label={t('intake.removeFile', { name: file.name })} onClick={() => dispatch({ type: 'remove', index })}>{t('intake.remove')}</Button>
                  </Row>)}
                </Stack>
                {draft.fileErrors.map(({ key, values }, index) => <Alert key={index} tone="danger">{t(key, values)}</Alert>)}
                {intakeError && intakeError !== conflict && !promptMessage && !documentMessage && <div data-testid="intake-error"><Alert tone="danger">{describeError(intakeError)}</Alert></div>}
                {canEdit && <Row>
                  <Button variant="primary" type="submit" data-testid="intake-submit" disabled={!dirty || busy || !access.verified}>
                    {t(submitting ? 'intake.working' : data?.id ? 'intake.add' : 'intake.submit')}
                  </Button>
                  {dirty && <ConfirmDestructive trigger={<Button variant="danger" disabled={busy}>{t('intake.discard')}</Button>}
                    title={t('intake.discardTitle')} description={t('intake.discardDescription')} action={t('intake.discard')}
                    onConfirm={() => { dispatch({ type: 'clear' }); write.reset(); setPromptTouched(false) }} />}
                </Row>}
              </Stack>
            </form>
          </SettingsSection>
          {!!data?.sources.length && <SettingsSection title={t('intake.sources')}>
            <Table label={t('intake.sources')} columns={['name', 'kind', 'pages', 'chunks', 'chars'].map(id => ({ id, label: t(`intake.source.${id}`) }))}
              rows={data.sources.map((source, index) => ({ id: String(index), cells: [
                t('common.serverText', { text: source.name }), t('common.serverText', { text: source.kind }),
                ...[source.pages, source.chunks, source.chars].map(text => t('common.serverText', { text })),
              ] }))} />
          </SettingsSection>}
          {!!questions.length && <div data-testid="questions"><SettingsSection title={t('intake.questions')}>
            {questions.map(question => <RequirementQuestionCard key={question.id} question={question} canEdit={canEdit} busy={busy} write={write.mutateAsync} />)}
          </SettingsSection></div>}
          {!!items.length && <SettingsSection title={t('intake.start')}>
            {!!phases.length && <Stack gap={2}>
              <h3>{t('intake.phases')}</h3>
              <ol className="v2-guided-list">{phases.map(item => <li key={item.number}>{t('intake.phaseCount', { name: item.name, count: item.items })}</li>)}</ol>
            </Stack>}
            {canEdit && <>
              {!!phases.length && <Field label={t('intake.phase')} error={fieldMessage(startRun.error, 'phase')}>{attrs => <Select triggerProps={attrs}
                value={String(phase?.number)} options={phases.map(item => ({ value: String(item.number), label: t('common.serverText', { text: item.name }) }))}
                disabled={busy} onValueChange={value => { startRun.reset(); void navigate({ search: previous => ({ ...previous, phase: Number(value) }), replace: true }) }} />}</Field>}
              <Field label={t('intake.workspace')} error={fieldMessage(startRun.error, 'workspace_id')}>{attrs => <Select triggerProps={attrs}
                value={workspace?.id ?? 'new'} options={[{ value: 'new', label: t('intake.newWorkspace') },
                  ...availableWorkspaces.map(item => ({ value: item.id, label: t('common.serverText', { text: item.name }) }))]}
                disabled={busy || workspaces.isPending || workspaces.isError}
                onValueChange={value => { startRun.reset(); void navigate({ search: previous => ({ ...previous, workspace: value === 'new' ? undefined : value }), replace: true }) }} />}</Field>
              {workspaceMissing && <Alert tone="warning" action={<Button onClick={() => {
                void navigate({ search: previous => ({ ...previous, workspace: undefined }), replace: true })
              }}>{t('intake.newWorkspace')}</Button>}>{t('intake.startWorkspaceMissing')}</Alert>}
              {workspaces.isError && <GuidedLoadError error={workspaces.error} retry={() => void workspaces.refetch()} label={t('intake.workspaceError')} />}
              {startRun.error && startRun.error !== conflict && !fieldMessage(startRun.error, 'phase') && !fieldMessage(startRun.error, 'workspace_id') && <Alert tone="danger">{describeError(startRun.error)}</Alert>}
              {!!conflictQuestions.length && <ul className="v2-guided-list">{conflictQuestions.map((text, index) => <li key={index}>{t('common.serverText', { text })}</li>)}</ul>}
              <Row>{openQuestions.length ? <Dialog open={confirm} onOpenChange={setConfirm}
                trigger={<Button variant="primary" data-testid="start-build" disabled={startDisabled}>{t('intake.start')}</Button>}
                title={t('intake.confirmAssumptions')} closeLabel={t('intake.goBackToQuestions')}
                description={t('intake.assumptionsWarning', { count: openQuestions.length })}
                actions={<Button variant="primary" disabled={busy} onClick={() => void start(true)}>{t('intake.acceptAndStart')}</Button>}>
                <div data-testid="confirm-assumptions" />
              </Dialog> : <Button variant="primary" data-testid="start-build" disabled={startDisabled} onClick={() => void start(false)}>{t('intake.start')}</Button>}</Row>
            </>}
            {!inScope && <p>{t('intake.noScope')}</p>}
          </SettingsSection>}
        </Stack>
        <Stack gap={4} data-testid="requirements-map">
          {items.length ? <SettingsSection title={t('intake.understood')}>
            {coverage && <strong data-testid="coverage-summary">
              {t('intake.coverage', { covered: coverage.covered, total: inScope, percent: coverage.percent_covered })}
              {!!coverage.out_of_scope && t('intake.excludedCount', { count: coverage.out_of_scope })}
            </strong>}
            <Row>
              {data?.status && <Badge tone={data.status === 'ready' ? 'success' : 'neutral'}>{t(`intake.mapStatus.${data.status}`)}</Badge>}
              <Badge>{t('intake.openQuestions', { count: openQuestions.length })}</Badge>
            </Row>
            {kinds.map(kind => {
              const grouped = pageItems.filter(item => item.kind === kind)
              return grouped.length ? <Stack key={kind} data-testid="req-group">
                <h3>{groups.includes(kind) ? t(`intake.groups.${kind}`) : t('common.serverText', { text: kind })}</h3>
                {grouped.map(item => <RequirementDetails key={item.id} item={item} canEdit={canEdit} busy={busy} write={write.mutateAsync} />)}
              </Stack> : null
            })}
            {pages > 1 && <Pagination label={t('intake.understood')} page={page} pages={pages}
              onChange={next => void navigate({ search: previous => ({ ...previous, page: next }) })} />}
          </SettingsSection> : <EmptyState title={t('intake.understood')} description={t('intake.empty')}
            action={canEdit && access.verified ? <Button onClick={() => prompt.current?.focus()}>{t('intake.focusPrompt')}</Button> : undefined} />}
        </Stack>
      </Grid>
    </>}
    <Dialog open={blocker.status === 'blocked'} onOpenChange={open => { if (!open && blocker.status === 'blocked') blocker.reset() }}
      title={t('intake.leaveTitle')} description={t('intake.discardDescription')}
      actions={<Button variant="danger" onClick={() => { if (blocker.status === 'blocked') blocker.proceed() }}>{t('intake.discard')}</Button>}>
      {null}
    </Dialog>
  </Stack>
}
