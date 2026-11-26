import { useQuery } from '@tanstack/react-query'
import { useReducer, useRef } from 'react'
import { useT } from '../../i18n'
import { Form, ReadOnlyNote } from '../../patterns'
import { Badge, Button, Dialog, Disclosure, EmptyState, Grid, Row, Select, Stack, Textarea } from '../../ui'
import { aiIssue, aiText } from '../../validators/operateAi'
import { uuidIssue } from '../../validators/operateRuntime'
import { newIdempotencyKey } from '../../../shell/money/moneyLogic'
import { agentHistoryOptions, agentRunOptions, registryOptions, runModes, runStatuses, statsOptions, useAiAccess, useStartAgent } from './api/ai'
import type { RunMode } from './api/ai'
import { runtimeError } from './api/live'
import type { LiveProps, Session } from './api/live'
import { canWrite } from './api/operate'
import type { AgentRegistry, AgentRun } from './api/tools'
import { AiActions, AiFeedback, AiPermission, AiRuntime, useAiFormat } from './components/AiRuntime'
import { SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Details, Empty, enumLabel, key, Pager, Panel, Pick, serverFields, text } from './components/Runtime'
import { JsonDetails } from './components/RuntimeTools'
import { agentStart, initialAgentStart, prepareAttempt } from './state/agentStart'
import type { AgentAttempt } from './state/agentStart'

type Agent = AgentRegistry['agents'][number]
const emptyAgents: Agent[] = []

export default function AgentRunsScreen(props: LiveProps) {
  return <AiRuntime id={props} title={'agentruns'}>{session => <AgentRuns session={session} writable={canWrite(props)} />}</AiRuntime>
}

function agentChoices(t: ReturnType<typeof useT>, agents: Agent[], first = 'allAgents') {
  return [{ value: '_none', label: t(key(first)) }, ...agents.map(agent => ({ value: agent.name, label: data(t, agent.name) }))]
}

function AgentRuns({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const format = useAiFormat()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const size = 20
  const page = search.page ?? 1
  const status = runStatuses.find(status => search.status === status)
  const registry = useQuery(registryOptions(session))
  const stats = useQuery(statsOptions(session, search.statsAgent))
  const runs = useQuery(agentHistoryOptions(session, { limit: size, offset: (page - 1) * size, agent: search.agent?.slice(0, 40), status }))
  const access = useAiAccess(session, writable)
  const [draft, dispatch] = useReducer(agentStart, initialAgentStart)
  const agents = registry.data?.agents ?? emptyAgents
  const selected = search.run && !uuidIssue(search.run) ? search.run : undefined
  const request = useStartAgent(session, draft.agent)
  const fresh = request.data?.data.id === selected ? request.data?.data : undefined
  const detail = useQuery(agentRunOptions(session, selected))
  const shown = detail.data ?? fresh
  const filtered = Boolean(search.agent || status)
  const clear = () => change({ agent: undefined, status: undefined, page: undefined })
  const focusAgent = () => document.querySelector<HTMLButtonElement>('[data-testid="start-agent"]')?.focus()
  const startAvailable = access.run && !registry.isError && agents.length > 0
  const settings = <SectionLink id={session.projectId} section="agentssettings" label={t(key('agentssettings'))} />
  return <Stack gap={4}>
    <AiActions id={session.projectId} settings="agentssettings" testId="agents-refresh" refresh={() => Promise.all([
      registry.refetch(), stats.refetch(), runs.refetch(), access.retry(), ...(selected ? [detail.refetch()] : []),
    ])}><SectionLink id={session.projectId} section="agentactions" label={t(key('agentactions'))} /></AiActions>
    <p className="v2-muted" data-testid="agents-note">{t(key('agentsNote'))}</p>
    <Panel title={'agentStats'}>
      <Pick label={t(key('statsAgent'))} value={search.statsAgent ?? ''} options={agentChoices(t, agents)}
        onChange={statsAgent => change({ statsAgent: statsAgent || undefined })} />
      {stats.isPending || stats.isError ? <AiFeedback error={stats.error} retry={stats.refetch} /> :
        stats.data.agents.length ? <Columns label={'agentStats'} names={['agent', 'runs', 'proposals', 'executed', 'rejected', 'pending', 'outcomeCounts', 'successRate']}
          rows={stats.data.agents.map(row => ({ id: row.agent, testId: 'stats-row', cells: [
            data(t, row.agent), ...[row.runs, row.proposals, row.executed, row.rejected, row.pending].map(format.count),
            t(key('triple'), { worked: format.count(row.outcome_success), failed: format.count(row.outcome_failure), neutral: format.count(row.outcome_neutral) }),
            row.success_rate_bp == null ? t(key('noOutcomes')) : format.bp(row.success_rate_bp),
          ] }))} /> : <Empty message="noAgentActivity" onAction={stats.refetch} />}
    </Panel>
    <Panel title={'agentRegistry'}>
      {registry.isPending || registry.isError ? <AiFeedback error={registry.error} retry={registry.refetch} /> :
        agents.length ? <Registry agents={agents} actions={registry.data.actions} /> :
          <EmptyState title={t(key('noRegisteredAgents'))} action={settings} />}
    </Panel>
    <Panel title={'startAgentRun'}>
      <AiPermission access={access}>
        {!access.run ? <ReadOnlyNote>{t(key('agentReadOnly'))}</ReadOnlyNote> :
          registry.isPending ? <AiFeedback retry={registry.refetch} /> : !startAvailable ?
            <EmptyState title={t(key('noStartAgent'))} action={settings} /> :
            <StartRun draft={draft} dispatch={dispatch} agents={agents} request={request} onStarted={id => change({ run: id, page: undefined })} />}
      </AiPermission>
    </Panel>
    {selected && <Panel title={'agentRunDetail'}>
      <Row><Button onClick={() => change({ run: undefined })}>{t(key('close'))}</Button></Row>
      {shown ? <div data-testid={fresh ? 'start-ok' : undefined}>
        {fresh && <p role="status">{t(key(request.data?.replayed ? 'replayed' : 'runStarted'))}</p>}
        <RunDetail run={shown} session={session} agent={agents.find(agent => agent.name === shown.agent)} />
      </div> : <AiFeedback error={detail.error} retry={detail.refetch} />}
      {shown && detail.isError && <AiFeedback error={detail.error} retry={detail.refetch} />}
    </Panel>}
    <Panel title={'runHistory'}>
      <Grid><Pick label={t(key('historyAgent'))} value={search.agent ?? ''} options={agentChoices(t, agents)}
        onChange={agent => change({ agent: agent || undefined, page: undefined })} />
        <Pick label={t(key('status'))} value={status ?? ''} options={choices(t, runStatuses, 'allStatuses')}
          onChange={status => change({ status: status || undefined, page: undefined })} /></Grid>
      {filtered && <Row><Button onClick={clear}>{t(key('clearFilters'))}</Button></Row>}
      {runs.isPending || runs.isError ? <AiFeedback error={runs.error} retry={runs.refetch} /> :
        runs.data.items.length ? <Columns label={'agentHistory'} names={['created', 'agent', 'mode', 'effectiveAutonomy', 'status', 'proposals', 'startedBy', 'agentRunDetail']}
          rows={runs.data.items.map(run => ({ id: run.id, testId: 'run-row', cells: [
            date(run.created_at), data(t, run.agent), enumLabel(t, run.mode), enumLabel(t, run.effective_autonomy),
            t(key(run.error_code ? 'statusCode' : 'value'), { value: enumLabel(t, run.status), code: run.error_code ?? '' }),
            format.count(run.proposals.length), data(t, run.started_by),
            <Button data-testid="run-open" aria-label={t(key('showRun'), { name: run.agent, when: date(run.created_at) })}
              onClick={() => change({ run: run.id })}>{t(key('show'))}</Button>,
          ] }))} /> :
          <EmptyState title={t(key(filtered ? 'noFilteredRuns' : 'noAgentRuns'))} action={filtered ?
            <Button onClick={clear}>{t(key('clearFilters'))}</Button> :
            startAvailable ? <Button onClick={focusAgent}>{t(key('startAgentRun'))}</Button> : settings} />}
      <Pager label={'agentHistory'} page={page} total={runs.data?.total ?? 0} size={size} change={page => change({ page })} />
    </Panel>
  </Stack>
}

function Registry({ agents, actions }: AgentRegistry) {
  const t = useT()
  const format = useAiFormat()
  return <Stack>
    <Columns label={'agentRegistry'} names={['agent', 'stage', 'configuredAutonomy', 'allowedActions', 'maxActions', 'requiredEval']}
      rows={agents.map(agent => ({ id: agent.name, testId: 'registry-agent', cells: [
        data(t, agent.name), data(t, agent.stage), enumLabel(t, agent.autonomy), data(t, agent.actions.join(', ')),
        format.count(agent.max_actions_per_run), agent.require_eval ? <Stack gap={1}>
          {data(t, agent.require_eval)}
          {agent.eval_ready != null && <Badge tone={agent.eval_ready ? 'success' : 'warning'}>
            {t(key(agent.eval_ready ? 'passed' : 'awaitingPass'))}</Badge>}
        </Stack> : data(t, null),
      ] }))} />
    <Disclosure label={t(key('actionDefinitions'))}>{actions.length ?
      <Columns label={'actionDefinitions'} names={['action', 'kind', 'risk', 'configuredAutonomy', 'description', 'targetFields']}
        rows={actions.map(action => ({ id: action.name, testId: 'registry-action', cells: [
          data(t, action.name), data(t, action.kind), enumLabel(t, action.risk), enumLabel(t, action.max_autonomy),
          data(t, action.description), data(t, [action.entity, ...action.fields].filter(Boolean).join(' · ')),
        ] }))} /> : <p>{t(key('noRegisteredActions'))}</p>}
    </Disclosure>
  </Stack>
}

function StartRun({ draft, dispatch, agents, request, onStarted }: {
  draft: typeof initialAgentStart; dispatch: React.Dispatch<Parameters<typeof agentStart>[1]>;
  agents: Agent[]; request: ReturnType<typeof useStartAgent>; onStarted: (id: string) => void
}) {
  const t = useT()
  const trigger = useRef<HTMLButtonElement>(null)
  const chosen = agents.find(agent => agent.name === draft.agent)
  const ceiling = runModes.findIndex(mode => mode === chosen?.autonomy)
  const mode = draft.mode || (ceiling < 0 ? 'suggest' : runModes[ceiling])
  const confirm = draft.attempt
  const code = runtimeError(request.error)?.code
  const start = (attempt: AgentAttempt) => {
    if (request.isPending) return
    request.mutate({ goal: attempt.goal, mode: attempt.mode, idempotency_key: attempt.key }, {
      onSuccess: result => {
        dispatch({ type: 'complete' })
        onStarted(result.data.id)
      },
      onError: () => dispatch({ type: 'close' }),
    })
  }

  return <Stack>
    <Form key={draft.revision} preserveFocusOnSubmit fields={[
      { name: 'agent', label: t(key('agent')), errorTestId: 'start-error',
        validateWith: value => agents.some(agent => agent.name === value) ? undefined : aiIssue('chooseAgent'),
        control: ({ name, disabled, ...attrs }) => <Select name={name} disabled={disabled} triggerProps={{ ...attrs, 'data-testid': 'start-agent' }}
          options={agentChoices(t, agents, 'choose')} value={draft.agent || '_none'}
          onValueChange={agent => dispatch({ type: 'agent', agent: agent === '_none' ? '' : agent })} /> },
      { name: 'mode', label: t(key('mode')),
        control: ({ name, disabled, ...attrs }) => <Select name={name} disabled={disabled} triggerProps={{ ...attrs, 'data-testid': 'start-mode' }}
          options={choices(t, runModes.slice(0, ceiling + 1), 'agentDefault')} value={draft.mode || '_none'}
          onValueChange={value => dispatch({ type: 'mode', mode: (value === '_none' ? '' : value) as RunMode | '' })} /> },
      { name: 'goal', label: t(key('goal')), validateWith: aiText('describeGoal', 4000), errorTestId: chosen ? 'start-error' : undefined,
        control: attrs => <Textarea {...attrs} maxLength={4000} data-testid="start-goal" /> },
    ]} layout={fields => <Stack><Grid>{fields.agent}{fields.mode}</Grid>{fields.goal}</Stack>}
      pending={request.isPending} serverErrors={serverFields(request.error)}
      submitProps={{ ref: trigger, className: 'v2-ai-start', 'data-testid': 'start-run' }}
      submitLabel={t(key(request.isPending ? 'startingAgent' : mode === 'suggest' ? 'startDry' : 'startLive'))}
      onSubmit={form => {
        const attempt = prepareAttempt(draft.attempt, draft.agent, text(form, 'goal'), mode, newIdempotencyKey)
        dispatch({ type: 'prepare', attempt })
        if (mode === 'suggest') start(attempt)
      }}>
      {chosen && <p data-testid="start-mode-note">{t(key('modeNote'), { mode: enumLabel(t, mode), behavior: t(key('mode_' + mode)) })}</p>}
      {mode === 'auto' && chosen?.require_eval && chosen.eval_ready === false &&
        <p>{t(key('evalRequired'), { suite: chosen.require_eval })}</p>}
    </Form>
    {draft.confirm && confirm && <Dialog title={t(key('confirmRun'))}
      description={t(key('confirmRunHelp'), { agent: confirm.agent, mode: enumLabel(t, confirm.mode), behavior: t(key('mode_' + confirm.mode)) })}
      open={draft.confirm} returnFocus={trigger} onOpenChange={open => {
        if (!open && !request.isPending) dispatch({ type: 'close' })
      }} actions={<Button variant="primary" className="v2-ai-confirm" data-testid="start-yes" disabled={request.isPending} onClick={() => start(confirm)}>
        {t(key(request.isPending ? 'startingAgent' : 'confirmRunMode'), { mode: enumLabel(t, confirm.mode) })}
      </Button>}>
      {null}
    </Dialog>}
    {request.error && <div data-testid="start-write-error"><AiFeedback error={request.error} write
      conflictLabel={code === 'retry_with_new_key' ? t(key('newRunKey')) : undefined}
      retry={() => {
        if (code === 'retry_with_new_key') dispatch({ type: 'newKey' })
        request.reset()
      }} /></div>}
  </Stack>
}

function RunDetail({ run, session, agent }: { run: AgentRun; session: Session; agent?: Agent }) {
  const t = useT()
  const date = useOperateDate()
  return <Stack data-testid="agent-run-detail">
    <Row><span data-testid="run-status"><Badge tone={run.status === 'completed' ? 'success' : 'danger'}>{data(t, run.status)}</Badge></span>
      <span>{data(t, run.agent)}</span><span>{date(run.created_at)}</span>
    </Row>
    {run.error_code && <p>{t(key('caseError'), { code: run.error_code })}</p>}
    <p data-testid="run-goal" className="v2-ai-reader">{t(key('runGoalText'), { goal: run.goal })}</p>
    <Details values={[
      ['configuredAutonomy', agent ? enumLabel(t, agent.autonomy) : data(t, null)],
      ['requestedMode', enumLabel(t, run.mode)],
      ['effectiveAutonomy', <span data-testid="run-effective">{enumLabel(t, run.effective_autonomy)}</span>],
    ]} />
    {run.proposals.length ? <Columns label={'runProposals'} names={['action', 'kindRisk', 'status', 'allowedAutonomy', 'arguments', 'resultReason']}
      rows={run.proposals.map(proposal => ({ id: proposal.id, testId: 'run-proposal', cells: [
        data(t, proposal.action), t(key('pair'), { left: proposal.kind, right: enumLabel(t, proposal.risk) }),
        enumLabel(t, proposal.status), enumLabel(t, proposal.allowed_autonomy),
        <JsonDetails label={'arguments'} value={proposal.args} />,
        <Stack gap={1}>
          {proposal.error_code && <span>{t(key('caseError'), { code: proposal.error_code })}</span>}
          {proposal.reason && <span>{data(t, proposal.reason)}</span>}
          {proposal.result && <JsonDetails label={'actionResult'} value={proposal.result} />}
          {proposal.outcome && <span>{t(key('proposalOutcome'), { outcome: enumLabel(t, proposal.outcome) })}</span>}
          {!proposal.error_code && !proposal.reason && !proposal.result && !proposal.outcome && data(t, null)}
        </Stack>,
      ] }))} /> : <p data-testid="run-no-proposals">{t(key('noRunProposals'))}</p>}
    <Row><SectionLink id={session.projectId} section="agentactions" label={t(key('reviewRunProposals'))} search={{ preview: session.target.id, run: run.id, status: 'all' }} /></Row>
  </Stack>
}
