import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useRouter, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { isLive, runActions } from '../../../shell/ai/buildLogic'
import { redactJson } from '../../../shell/workbench/workbenchLogic'
import { effectiveState } from '../../../shell/ai/approvalLogic'
import { useT } from '../../i18n'
import { Form, PageHeader, ReadOnlyNote, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Card, CodeBlock, Dialog, EmptyState, Grid, Pagination, Progress, Row, Select, Skeleton, Stack, Tabs, Textarea } from '../../ui'
import { deliveryLimits, validators } from '../../validators'
import { deliveryApi, deliveryKeys, inboxOptions, runOptions, runsOptions, usePlatformBudget, useRunAction, workspaceOptions } from './api/delivery'
import type { GateRunResult, Run } from './api/delivery'
import { useGuidedAccess, useGuidedWorkspaces } from './api/guided'
import { ApprovalLink, ConfirmAction, DeliveryError, ProjectLink } from './components/DeliveryControls'
import { GuidedLoadError } from './components/GuidedFeedback'
import { DraftFiles, formatGuidedDate, WorkspacePanel } from './components/WorkspacePanel'
import './guided.css'

const route = '/projects/$projectId/$section'
const tabs = ['gates', 'details', 'plan', 'diagrams', 'api', 'stage']
const allStates = ['']
const money = (value: number) => new Intl.NumberFormat(undefined, {
  style: 'currency', currency: 'USD', minimumFractionDigits: value < 1_000_000 ? 4 : 2,
}).format(value / 1_000_000)

function NewRun({ projectId }: { projectId: string }) {
  const t = useT()
  const navigate = useNavigate({ from: route })
  const client = useQueryClient()
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const workspaces = useGuidedWorkspaces(projectId, open)
  const start = useMutation({
    mutationFn: ({ goal, workspace }: { goal: string; workspace: string }) => deliveryApi.createRun(projectId, goal, workspace || null),
    onMutate: () => router.state.location.href,
    onSuccess: async (run, _variables, from) => {
      setOpen(false)
      await client.invalidateQueries({ queryKey: deliveryKeys.runs(projectId) })
      if (router.state.location.href === from) {
        await navigate({ search: previous => ({ ...previous, history: undefined, page: undefined, run: run.id }) })
      }
    },
  })
  return <Dialog title={t('build.newRun')} open={open} onOpenChange={value => { setOpen(value); start.reset() }}
    trigger={<Button>{t('build.newRun')}</Button>}>
    <Stack>
      <DeliveryError error={start.error} reload={() => { start.reset(); void workspaces.refetch() }} />
      {workspaces.isError && <GuidedLoadError error={workspaces.error} label={t('build.workspaceError')} retry={() => void workspaces.refetch()} />}
      <Form pending={start.isPending} submitLabel={t('build.start')} fields={[
        { name: 'goal', label: t('build.goal'), validate: [validators.required, validators.length(deliveryLimits.goal)], control: attrs => <Textarea {...attrs} /> },
        { name: 'workspace', label: t('build.workspaces'), control: ({ name, disabled, ...attrs }) => <Select name={name} disabled={disabled} triggerProps={attrs} defaultValue="new"
          options={[{ value: 'new', label: t('build.newWorkspaceOption') }, ...(workspaces.data ?? []).filter(item => item.state === 'active').map(item => ({ value: item.id, label: item.name }))]} /> },
      ]} onSubmit={data => start.mutate({ goal: String(data.get('goal')).trim(), workspace: data.get('workspace') === 'new' ? '' : String(data.get('workspace') ?? '') })} />
    </Stack>
  </Dialog>
}

export default function BuildScreen() {
  const t = useT()
  const { projectId } = useParams({ from: route })
  const { run, history = 1 } = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const runs = useQuery(runsOptions(projectId, history))
  const access = useGuidedAccess(projectId)
  const write = access.role === 'owner' || access.role === 'editor'
  const current = run ?? runs.data?.items[0]?.id
  return <Stack gap={5} data-testid="build-page">
    <PageHeader title={t('nav.build')} description={t('build.intro')} actions={write && access.verified && <NewRun projectId={projectId} />} />
    {access.failed && <GuidedLoadError error={access.account.error ?? access.members.error} retry={access.retry} label={t('guided.accessError')} />}
    {!access.failed && !access.pending && !write && <ReadOnlyNote />}
    {write && !access.verified && <Alert>{t('guided.verify')}</Alert>}
    {runs.isError && <GuidedLoadError error={runs.error} label={t('build.loadError')} retry={() => void runs.refetch()} />}
    {runs.isPending && !run && <Card><Skeleton lines={8} label={t('build.loading')} /></Card>}
    {runs.data && <Stack>
        {runs.data.items.length > 0 && <Row>
          <Select value={runs.data.items.some(item => item.id === current) ? current : undefined}
            placeholder={t('build.history')} triggerProps={{ 'aria-label': t('build.history') }}
            options={runs.data.items.map(item => ({ value: item.id, label: item.goal }))}
            onValueChange={value => void navigate({ search: previous => ({ ...previous, page: undefined, run: value }) })} />
        </Row>}
        <Pagination label={t('build.history')} page={history} pages={Math.ceil(runs.data.total / 20)}
          onChange={value => void navigate({ search: previous => ({ ...previous, history: value, run: undefined, page: undefined }) })} />
        {!current && <Stack>
            <EmptyState title={t('build.empty')} action={<ProjectLink primary projectId={projectId} section="intake">{t('build.describe')}</ProjectLink>} />
            <WorkspacePanel projectId={projectId} write={write} />
          </Stack>}
      </Stack>}
    {current && <BuildRun key={current} projectId={projectId} id={current} write={write} owner={access.role === 'owner'} verified={access.verified} />}
  </Stack>
}

function BudgetTiles({ projectId, run }: { projectId: string; run: Run }) {
  const t = useT()
  const budget = usePlatformBudget(projectId)
  const rows = [
    { key: 'steps', used: run.steps_used, cap: run.budgets.max_steps },
    { key: 'repairs', used: run.repairs_used, cap: run.budgets.max_repairs },
    { key: 'cost', used: run.cost_micro_usd, cap: run.budgets.max_cost_micro_usd },
    ...(budget.data ? [{ key: 'platform', used: budget.data.spent_micro_usd, cap: budget.data.cap_micro_usd }] : []),
  ]
  return <Stack>
    <Grid className="v2-delivery-tiles">
      {rows.map(({ key, used, cap }) => {
        const label = t('build.' + key)
        const value = key === 'cost' || key === 'platform' ? money(used) : used
        const limit = typeof cap === 'number' && cap > 0 ? cap : undefined
        return <Card key={key}><Stack gap={1}>
          <strong>{label}</strong>
          <span>{limit === undefined ? value : t('build.budgetOf', { used: value, limit: typeof value === 'number' ? limit : money(limit) })}</span>
          {limit !== undefined && <Progress label={label} value={key === 'platform' ? used + (budget.data?.reserved_micro_usd ?? 0) : used} max={limit} />}
          {key === 'platform' && typeof budget.data?.remaining_micro_usd === 'number' && <span>{t('build.remaining', { amount: money(budget.data.remaining_micro_usd) })}</span>}
        </Stack></Card>
      })}
    </Grid>
    {budget.failed && <GuidedLoadError error={null} label={t('build.budgetError')} retry={budget.retry} />}
    {budget.data?.remaining_micro_usd === 0 && <Alert tone="warning">{t('build.budgetLimit')}</Alert>}
  </Stack>
}

function BuildRun({ projectId, id, write, verified, owner }: { projectId: string; id: string; write: boolean; verified: boolean; owner: boolean }) {
  const t = useT()
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const run = useQuery(runOptions(projectId, id, search.page))
  const approvals = useQuery(inboxOptions(projectId, allStates, id, Boolean(run.data && isLive(run.data))))
  const action = useRunAction(projectId, id)
  const drive = useRunAction(projectId, id)
  const rows = approvals.data?.rows ?? []

  if (run.isPending) return <Card><Skeleton lines={8} label={t('build.loading')} /></Card>
  if (!run.data) return <GuidedLoadError error={run.error} label={t('build.loadError')} retry={() => void run.refetch()} />
  const current = run.data
  const pending = rows.filter(row => effectiveState(row) === 'pending')
  const plan = rows.find(row => row.kind === 'A' && row.payload.extension !== true)
  const commands = runActions(current, pending.length)
  const report = action.variables === 'gates' ? action.data as GateRunResult | undefined : undefined
  const tab = tabs.includes(search.tab ?? '') ? search.tab! : 'gates'
  const stopped = current.stop_code
  const workspace = current.workspace_id ?? undefined
  const view: Record<string, React.ReactNode> = {
    gates: <SettingsSection title={t('build.gates')} description={t('build.gatesIntro')}>
      {approvals.isPending && <Skeleton />}
      {approvals.isError && <GuidedLoadError error={approvals.error} label={t('approval.loadError')} retry={() => void approvals.refetch()} />}
      {approvals.isSuccess && !rows.length && <p>{t('build.noApprovals')}</p>}
      {rows.map(row => <Row key={row.id}><ApprovalLink projectId={projectId} approval={row} /><Badge>{t('approval.states.' + effectiveState(row))}</Badge></Row>)}
      {report && <Stack>
        <Alert tone={report.ok ? 'success' : 'danger'}>{report.ok ? t('build.checksPassed') : t('build.checksFailed', { count: report.failure_count })}</Alert>
        {report.failures.map((failure, index) => <CodeBlock key={index} code={JSON.stringify(failure, null, 2)} />)}
        {report.failures.length < report.failure_count && <p>{t('build.reportLimit', { shown: report.failures.length, total: report.failure_count })}</p>}
        <CodeBlock label={t('build.reportHash')} code={report.report_hash} />
      </Stack>}
    </SettingsSection>,
    details: <SettingsSection title={t('build.details')}>
      <p>{t('build.runId', { run: current.id })}</p>
      <p>{t('build.started', { date: formatGuidedDate(current.started_at) })}</p>
      <p>{t('build.finished', { date: formatGuidedDate(current.finished_at) })}</p>
      <p>{t('build.updated', { date: formatGuidedDate(current.updated_at) })}</p>
      {workspace && tab === 'details' && <RunWorkspace projectId={projectId} workspace={workspace} />}
    </SettingsSection>,
    plan: <SettingsSection title={t('nav.plan')}>
      {plan ? <Stack><Badge>{t('approval.states.' + effectiveState(plan))}</Badge>
        {plan.payload.plan != null && <CodeBlock label={t('nav.plan')} code={JSON.stringify(plan.payload.plan, null, 2)} />}
        <Row><ApprovalLink projectId={projectId} approval={plan} /></Row>
      </Stack> : <p>{t('build.noPlan')}</p>}
    </SettingsSection>,
    diagrams: <SettingsSection title={t('build.diagrams')}>
      <Row><ProjectLink projectId={projectId} section="diagrams">{t('build.openDiagrams')}</ProjectLink></Row>
    </SettingsSection>,
    api: <SettingsSection title={t('build.api')}>
      <Row><ProjectLink projectId={projectId} section="see" search={{ workspace, view: 'reference' }}>{t('build.openPreview')}</ProjectLink></Row>
    </SettingsSection>,
    stage: <Stack>
      {workspace ? <><DraftFiles projectId={projectId} workspace={workspace} run={id} />
        <Row>
          <ProjectLink projectId={projectId} section="see" search={{ workspace, view: 'logs' }}>{t('preview.logs')}</ProjectLink>
          <ProjectLink projectId={projectId} section="see" search={{ workspace, view: 'data' }}>{t('preview.data')}</ProjectLink>
        </Row></> : <p>{t('build.noDraft')}</p>}
      <WorkspacePanel projectId={projectId} workspaceId={workspace} write={write} />
    </Stack>,
  }

  return <Stack data-testid="build-run" gap={5}>
    <Card><Stack>
      <h2>{current.goal}</h2>
      <Row><Badge tone={current.state === 'applied' ? 'success' : 'info'}>{t('build.states.' + current.state)}</Badge>
        <Badge>{t('build.phase', { phase: current.phase })}</Badge>
        <Badge>{t('build.ai')}</Badge>
        {commands.paused && <Badge>{t('build.paused')}</Badge>}
        {stopped && <Badge tone="warning">{stopped}</Badge>}
      </Row>
      {write && <Row>
        {commands.pause && <Button data-testid="run-pause" disabled={action.isPending} onClick={() => action.mutate('pause')}>{t('build.pause')}</Button>}
        {commands.gates && <Button data-testid="run-gates" disabled={action.isPending} onClick={() => {
          void navigate({ search: previous => ({ ...previous, tab: 'gates' }) }); action.mutate('gates')
        }}>{t('build.runGates')}</Button>}
        {commands.resume && verified && <Button variant="primary" data-testid="run-resume"
          disabled={drive.isPending || action.isPending || approvals.isPending || approvals.isError || pending.length > 0 || stopped === 'apply_conflict' && !owner}
          onClick={() => drive.mutate('resume')}>{t(current.state === 'created' ? 'build.start' : 'build.resume')}</Button>}
        {commands.cancel && ['cancel', 'takeover'].map(kind => <ConfirmAction key={kind}
          label={t('build.' + kind)} title={t('build.' + kind + 'Title')} description={t('build.cancelBody')}
          pending={action.isPending} onConfirm={() => action.mutateAsync('cancel')} testId={'run-' + kind} />)}
      </Row>}
      {drive.isPending && <p role="status">{t('build.driving')}</p>}
      <DeliveryError error={action.error} reload={() => { action.reset(); void run.refetch(); void approvals.refetch() }} />
      <DeliveryError error={drive.error} reload={() => { drive.reset(); void run.refetch(); void approvals.refetch() }} />
      {run.isError && <GuidedLoadError error={run.error} label={t('build.loadError')} retry={() => void run.refetch()} />}
      {stopped && <Alert tone="warning">{['apply_conflict', 'apply_failed', 'repair_limit'].includes(stopped) ? t('build.stop.' + stopped) : current.stop_detail ?? stopped}</Alert>}
      {current.state === 'applied' && <Alert tone="success" action={<ProjectLink projectId={projectId} section="see" primary>{t('nav.see')}</ProjectLink>}>{t('build.applied')}</Alert>}
    </Stack></Card>
    <BudgetTiles projectId={projectId} run={current} />
    <Grid className="v2-guided-columns">
      <SettingsSection title={t('build.timeline')}>
        {!current.steps.length && <p>{t('build.noSteps')}</p>}
        {current.steps.length > 0 && <ol className="v2-guided-list">{current.steps.map(step => <li key={step.id}>
          <Stack gap={1}><Row><strong>{t('build.step', { number: step.seq, name: step.tool_name ?? step.kind })}</strong>
            <Badge tone={step.ok ? 'success' : 'danger'}>{t(step.ok ? 'build.ok' : 'build.failed')}</Badge>
            {typeof step.output?.cost_micro_usd === 'number' && <span>{money(step.output.cost_micro_usd)}</span>}</Row>
            {step.output?.draft === 'applied' && <p>{t('build.applied')}</p>}
            {step.output?.draft === 'discarded' && <p>{t('build.discarded')}</p>}
            {step.output?.apply_conflict === true && <p>{t('build.stop.apply_conflict')}</p>}
            {step.output?.apply_failed === true && <p>{t('build.stop.apply_failed')}</p>}
            <details><summary>{t('build.stepDetails')}</summary>
              <CodeBlock code={JSON.stringify({ state: step.state, model: step.model, input: redactJson(step.input), output: redactJson(step.output), prompt_hash: step.prompt_hash, tool_set_hash: step.tool_set_hash }, null, 2)} />
            </details>
          </Stack>
        </li>)}</ol>}
        <Pagination label={t('build.timeline')} page={search.page ?? 1} pages={Math.ceil(current.steps_total / 200)}
          onChange={page => void navigate({ search: previous => ({ ...previous, page }) })} />
      </SettingsSection>
      {pending.length > 0 && <SettingsSection title={t('approval.pending')}>{pending.map(approval => <Row key={approval.id}>
        <Badge>{t('approval.gate', { kind: approval.kind })}</Badge><ApprovalLink projectId={projectId} approval={approval} />
      </Row>)}</SettingsSection>}
    </Grid>
    <Tabs label={t('build.views')} value={tab} onChange={tab => void navigate({ search: previous => ({ ...previous, tab }) })}
      items={tabs.map(id => ({ id, label: t('build.tabs.' + id), content: view[id] }))} />
  </Stack>
}

function RunWorkspace({ projectId, workspace }: { projectId: string; workspace: string }) {
  const t = useT()
  const query = useQuery(workspaceOptions(projectId, workspace))
  if (query.isPending) return <Skeleton />
  if (query.isError) return <GuidedLoadError error={query.error} label={t('build.workspaceError')} retry={() => void query.refetch()} />
  return <Stack gap={1}>
    <p>{t('build.workspaceId', { workspace: query.data.name })}</p>
    <p>{t('build.workspaceVersion', { branch: query.data.branch, version: query.data.spec_seq })}</p>
  </Stack>
}
