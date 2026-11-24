import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useRouter, useSearch } from '@tanstack/react-router'
import { useReducer } from 'react'
import { createdId, crudComplete, editedBody, entitiesOf, evidence, exampleBody, isLivePreview, isReady, itemPath, judge } from '../../../shell/ai/seeItLogic'
import { parseOperations } from '../../../shell/workbench/workbenchLogic'
import type { Entity } from '../../../shell/ai/seeItLogic'
import { useT } from '../../i18n'
import { PageHeader, ReadOnlyNote, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Card, CodeBlock, EmptyState, Field, Grid, Row, Select, Skeleton, Stack } from '../../ui'
import { deliveryApi, previewsOptions } from './api/delivery'
import type { Preview } from './api/delivery'
import { useGuidedAccess, useGuidedWorkspaces } from './api/guided'
import { previewDeadline, previewJson, previewKeys, previewOptions, previewRequest, usePreviewLifecycle } from './api/preview'
import { ConfirmAction, DeliveryError, ProjectLink } from './components/DeliveryControls'
import { GuidedLoadError } from './components/GuidedFeedback'
import { usePreviewCredentials } from './components/PreviewCredentials'
import { PreviewIdentity } from './components/PreviewIdentity'
import { PreviewTools } from './components/PreviewTools'
import { formatGuidedDate } from './components/WorkspacePanel'
import { checkReducer, initialChecks } from './state/preview'
import type { Check, Credential } from './state/preview'
import './guided.css'

const route = '/projects/$projectId/$section'
const checks: Check[] = ['list', 'create', 'read', 'update']
const live = (preview: Preview) => isLivePreview(preview.state) || preview.state === 'stopping'

export default function SeeScreen() {
  const t = useT()
  const { projectId } = useParams({ from: route })
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const router = useRouter()
  const access = useGuidedAccess(projectId)
  const workspaces = useGuidedWorkspaces(projectId, true)
  const previews = useQuery(previewsOptions(projectId))
  const { credentials } = usePreviewCredentials()
  const lifecycle = usePreviewLifecycle(projectId)
  const write = access.role === 'owner' || access.role === 'editor'
  const candidates = previews.data?.filter(item => (item.workspace_id ?? undefined) === search.workspace) ?? []
  const current = candidates.find(item => item.id === search.preview)
    ?? candidates.find(item => live(item) && credentials[item.id])
    ?? candidates.find(live)
  const detail = useQuery({ ...previewOptions(projectId, current?.id ?? ''),
    initialData: current, staleTime: 2000,
  })
  const preview = detail.data
  const credential = preview ? credentials[preview.id] : undefined
  const ready = Boolean(preview && isReady(preview.state))
  const timedOut = preview?.state === 'starting' && Date.now() - Date.parse(preview.created_at) >= previewDeadline
  const starting = preview?.state === 'starting' && !timedOut
  const canStart = write && access.verified && !lifecycle.isPending && !starting

  async function select(action: { type: 'start'; workspace?: string } | { type: 'rotate'; id: string }) {
    const from = router.state.location.href
    const next = await lifecycle.mutateAsync(action)
    if (router.state.location.href !== from) return
    await navigate({ search: previous => ({ ...previous, workspace: next.workspace_id ?? undefined, preview: next.id, entity: undefined, tool: undefined, page: undefined }) })
  }

  function start() {
    if (preview && ready && credential) {
      void detail.refetch()
      return
    }
    void select({ type: 'start', workspace: search.workspace }).catch(() => undefined)
  }

  return <Stack gap={5} data-testid="seeit-page">
    <PageHeader title={t('nav.see')} description={t('preview.intro')} />
    {access.failed && <GuidedLoadError error={access.account.error ?? access.members.error} retry={access.retry} label={t('guided.accessError')} />}
    {!access.failed && !access.pending && !write && <ReadOnlyNote />}
    {write && !access.verified && <Alert>{t('guided.verify')}</Alert>}
    {previews.isPending ? <Card><Skeleton lines={8} label={t('preview.loading')} /></Card>
      : previews.isError ? <GuidedLoadError error={previews.error} label={t('preview.loadError')} retry={() => void previews.refetch()} />
      : <Stack gap={5}>
        <Row>
          <Field label={t('preview.source')}>{attrs => <Select triggerProps={attrs} value={search.workspace ?? 'saved'}
            options={[{ value: 'saved', label: t('preview.saved') }, ...(workspaces.data ?? []).filter(item => item.state === 'active' || item.id === search.workspace).map(item => ({ value: item.id, label: item.name }))]}
            onValueChange={value => void navigate({ search: previous => ({ ...previous, workspace: value === 'saved' ? undefined : value, preview: undefined, entity: undefined, tool: undefined, page: undefined }) })} />}</Field>
          {preview && write && <Button variant="primary" data-testid="seeit-start" disabled={!canStart} onClick={start}>{t(ready && credential ? 'preview.reuse' : 'preview.startAgain')}</Button>}
        </Row>
        {workspaces.isError && <GuidedLoadError error={workspaces.error} label={t('build.workspaceError')} retry={() => void workspaces.refetch()} />}
        <DeliveryError error={lifecycle.error} reload={() => { lifecycle.reset(); void previews.refetch() }} />
        {detail.isError && <GuidedLoadError error={detail.error} label={t('preview.loadError')} retry={() => void detail.refetch()} />}
        {lifecycle.isPending && !preview && <Card><Skeleton lines={5} label={t('preview.starting')} /></Card>}
        {timedOut && <Alert tone="warning">{t('preview.timeout')}</Alert>}
        {!preview && !lifecycle.isPending && <EmptyState title={t('preview.empty')}
          action={write ? <Button data-testid="seeit-start" variant="primary" disabled={!canStart} onClick={start}>{t('preview.start')}</Button>
            : <ProjectLink projectId={projectId} section="build">{t('approval.backBuild')}</ProjectLink>} />}
        {preview && <SettingsSection title={t('preview.session')}>
          <Row><Badge tone={ready ? 'success' : 'neutral'}>{t('preview.states.' + preview.state)}</Badge>
            <span>{t('preview.expires', { date: formatGuidedDate(preview.expires_at) })}</span>
            <span>{t('preview.lastRequest', { date: formatGuidedDate(preview.last_request_at) })}</span></Row>
          {starting && <Skeleton lines={2} label={t('preview.starting')} />}
          {preview.error && <Alert tone="danger">{preview.error}</Alert>}
          {ready && <Alert tone="success">{t('preview.ready')}</Alert>}
          <Row>
            {write && live(preview) && <ConfirmAction label={t('preview.rotate')} title={t('preview.rotate')}
              description={t('preview.rotateBody')} pending={lifecycle.isPending} destructive={false}
              onConfirm={() => select({ type: 'rotate', id: preview.id })} />}
            {ready && credential && <PreviewIdentity preview={preview} credential={credential} allowRegister={write} />}
          </Row>
          {ready && !credential && <p>{t('preview.noToken')}</p>}
          <details><summary>{t('preview.limits')}</summary><CodeBlock code={JSON.stringify(preview.limits, null, 2)} /></details>
        </SettingsSection>}
        {ready && preview && credential
          ? <PreviewChecks key={preview.id + ':' + credential.revision} projectId={projectId} preview={preview} credential={credential} write={write} />
          : <PendingChecks preview={ready ? 'pass' : starting || lifecycle.isPending ? 'sending' : preview?.state === 'failed' ? 'fail' : 'idle'} />}
        {previews.data.length > 0 && <SettingsSection title={t('preview.history')}>
          {previews.data.map(item => <Card key={item.id}><Stack>
            <Row className="v2-spread">
              <Stack gap={1}><strong>{item.id}</strong>
                <span>{workspaces.data?.find(workspace => workspace.id === item.workspace_id)?.name ?? (item.workspace_id || t('preview.saved'))}</span>
              </Stack>
              <Badge>{t('preview.states.' + item.state)}</Badge>
              <span>{t('preview.expires', { date: formatGuidedDate(item.expires_at) })}</span>
            </Row>
            <Row>
              <Button aria-pressed={preview?.id === item.id} onClick={() => void navigate({ search: previous => ({
                ...previous, workspace: item.workspace_id ?? undefined, preview: item.id, entity: undefined, tool: undefined, page: undefined,
              }) })}>{t('preview.open')}</Button>
              {write && !credentials[item.id] && live(item) && <ConfirmAction label={t('preview.reconnect')} title={t('preview.rotate')}
                description={t('preview.rotateBody')} destructive={false} pending={lifecycle.isPending}
                onConfirm={() => select({ type: 'rotate', id: item.id })} />}
              {write && live(item) && <ConfirmAction label={t('preview.stop')} title={t('preview.stopTitle')} description={t('preview.stopBody')}
                pending={lifecycle.isPending} onConfirm={() => lifecycle.mutateAsync({ type: 'stop', id: item.id })} />}
            </Row>
          </Stack></Card>)}
        </SettingsSection>}
      </Stack>}
  </Stack>
}

function PreviewChecks({ projectId, preview, credential, write }: {
  projectId: string; preview: Preview; credential: Credential; write: boolean
}) {
  const t = useT()
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const api = useQuery({
    queryKey: [...previewKeys.proxy(preview.id, credential.revision), 'openapi'],
    queryFn: () => previewJson<unknown>(preview, credential, '/openapi.json'), retry: false, gcTime: 0,
  })
  const entities = entitiesOf(api.data)
  const selected = entities.find(entity => entity.name === search.entity) ?? entities.find(crudComplete) ?? entities[0]
  const kit = useMutation({ mutationFn: () => deliveryApi.downloadKit(projectId, 'self-host-kit.zip') })

  return <Stack>
    {api.isPending && <Card><Skeleton lines={6} label={t('preview.loadingApi')} /></Card>}
    {api.isError && <>
      <GuidedLoadError error={api.error} label={t('preview.apiError')} retry={() => void api.refetch()} />
      <PendingChecks preview="pass" endpoints="fail" />
    </>}
    {api.isSuccess && <>
      {!selected && <>
        <EmptyState title={t('preview.noEntities')} action={<ProjectLink projectId={projectId} section="model">{t('preview.openModel')}</ProjectLink>} />
        <PendingChecks preview="pass" endpoints="fail" />
      </>}
      {selected && <GuidedChecks key={selected.name} entity={selected} entities={entities} preview={preview}
        credential={credential} doc={api.data} write={write}
        choose={entity => void navigate({ search: previous => ({ ...previous, entity, page: undefined }) })}
        kit={write ? <Stack>
          <Row><Button disabled={kit.isPending} onClick={() => kit.mutate()}>{t('preview.kit')}</Button></Row>
          <DeliveryError error={kit.error} reload={kit.reset} />
        </Stack> : undefined} />}
    </>}
    <PreviewTools preview={preview} credential={credential} doc={api.data} entities={entities} entity={selected} write={write} />
  </Stack>
}

function GuidedChecks({ entity, entities, preview, credential, doc, choose, write, kit }: {
  entity: Entity; entities: Entity[]; preview: Preview; credential: Credential; doc: unknown;
  choose: (entity: string) => void; write: boolean; kit?: React.ReactNode
}) {
  const t = useT()
  const client = useQueryClient()
  const [state, dispatch] = useReducer(checkReducer, initialChecks)
  const ops = { list: entity.list, create: entity.create, read: entity.read, update: entity.update }
  const run = useMutation({
    mutationFn: async (queue: Check[]) => {
      let record = state.record
      for (const check of queue) {
        const operation = ops[check]
        if (!operation) break
        if ((check === 'read' || check === 'update') && !record) break
        const path = check === 'read' || check === 'update' ? itemPath(entity, record!) : operation.path
        const body = check === 'create' ? exampleBody(doc, operation)
          : check === 'update' ? editedBody(exampleBody(doc, operation)) : undefined
        try {
          const response = await previewRequest(preview, credential, operation.method, path, body)
          const result = judge(check, response, record)
          if (check === 'create') record = result.ok ? createdId(response.json) ?? undefined : undefined
          dispatch({ type: 'result', check, record,
            result: { verdict: result.ok ? 'pass' : 'fail', status: response.status, ...evidence(operation.method, path, body, response) } })
          if (!result.ok) break
        } catch {
          dispatch({ type: 'result', check, result: { verdict: 'fail' } })
          break
        }
      }
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: [...previewKeys.proxy(preview.id, credential.revision), 'records'] }) },
  })
  const deleteEndpoint = parseOperations(doc).some(op => op.method === 'delete' && op.path === entity.read?.path)
  const remove = useMutation({
    mutationFn: async (id: string) => {
      await previewJson(preview, credential, itemPath(entity, id), 'DELETE')
    },
    onSuccess: () => {
      dispatch({ type: 'removed' })
      void client.invalidateQueries({ queryKey: [...previewKeys.proxy(preview.id, credential.revision), 'records'] })
    },
  })
  const busy = run.isPending || remove.isPending
  const outcomes = Object.values(state.results)
  const passed = 2 + outcomes.filter(result => result?.verdict === 'pass').length
  const failed = outcomes.filter(result => result?.verdict === 'fail').length
  return <Grid className="v2-guided-columns" data-testid="seeit-steps">
    <SettingsSection title={t('preview.checks')}>
      <Row><strong>{t('preview.steps.preview')}</strong><Badge tone="success">{t('preview.pass')}</Badge></Row>
      <Row><strong>{t('preview.steps.endpoints')}</strong><Badge tone="success">{t('preview.pass')}</Badge></Row>
      <Field label={t('preview.entity')}>{attrs => <Select triggerProps={attrs} value={entity.name} disabled={busy}
        options={entities.map(item => ({ value: item.name, label: item.name }))} onValueChange={choose} />}</Field>
      {checks.map(check => {
        const result = state.results[check]
        const op = ops[check]
        const missingRecord = (check === 'read' || check === 'update') && !state.record
        return <Card key={check}><Stack>
          <Row className="v2-spread">
            <strong>{t('preview.steps.' + check)}</strong>
            <Badge tone={result?.verdict === 'pass' ? 'success' : result ? 'danger' : 'neutral'}>{t('preview.' + (result?.verdict ?? 'idle'))}</Badge>
          </Row>
          {op ? <p>{t('preview.operation', { method: op.method.toUpperCase(), path: op.path })}</p> : <p>{t('preview.noEndpoint')}</p>}
          {missingRecord && <p>{t('preview.createFirst')}</p>}
          {result && result.status === undefined && <Alert tone="danger">{t('preview.network')}</Alert>}
          {result?.status === 401 && <Alert tone="warning">{t('preview.authRequired')}</Alert>}
          {result?.request && <details open={result.verdict === 'fail' || undefined}><summary>{t('preview.evidence')}</summary>
            <Stack><CodeBlock label={t('preview.request')} code={result.request} /><CodeBlock label={t('preview.response')} code={result.response ?? ''} /></Stack>
          </details>}
          {(write || check === 'list' || check === 'read') && <Row><Button disabled={!op || missingRecord || busy}
            onClick={() => run.mutate([check])}>{t('preview.try')}</Button></Row>}
        </Stack></Card>
      })}
      {write && <Row><Button variant="primary" disabled={!crudComplete(entity) || busy}
        onClick={() => run.mutate(checks)}>{t(run.isPending ? 'preview.sending' : 'preview.runAll')}</Button>
        {deleteEndpoint && state.record && <ConfirmAction label={t('preview.delete')} title={t('preview.deleteTitle')}
          description={t('preview.deleteBody', { path: itemPath(entity, state.record) })} pending={busy}
          onConfirm={() => remove.mutateAsync(state.record!)} />}
      </Row>}
      {remove.isSuccess && !state.record && <Alert tone="success">{t('preview.removed')}</Alert>}
      <DeliveryError error={remove.error} reload={remove.reset} />
    </SettingsSection>
    <SettingsSection title={t('preview.acceptance')}>
      <p aria-live="polite">{t('preview.passed', { count: passed })}</p>
      {passed === 6 && <Alert tone="success">{t('preview.accepted')}</Alert>}
      {failed > 0 && <Alert tone="warning">{t('preview.failedChecks', { count: failed })}</Alert>}
      <p>{t('preview.cleanup')}</p>
      {passed === 6 && kit}
    </SettingsSection>
  </Grid>
}

function PendingChecks({ preview, endpoints = 'idle' }: { preview: string; endpoints?: string }) {
  const t = useT()
  return <Grid className="v2-guided-columns" data-testid="seeit-steps">
    <SettingsSection title={t('preview.checks')}>
      {['preview', 'endpoints', ...checks].map(step => {
        const status = step === 'preview' ? preview : step === 'endpoints' ? endpoints : 'idle'
        return <Row key={step} className="v2-spread">
          <strong>{t('preview.steps.' + step)}</strong>
          <Badge tone={status === 'pass' ? 'success' : status === 'fail' ? 'danger' : 'neutral'}>{t('preview.' + status)}</Badge>
        </Row>
      })}
    </SettingsSection>
    <SettingsSection title={t('preview.acceptance')}>
      <p>{t('preview.passed', { count: preview === 'pass' ? 1 : 0 })}</p>
      <p>{t('preview.cleanup')}</p>
    </SettingsSection>
  </Grid>
}
