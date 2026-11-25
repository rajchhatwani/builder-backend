import { useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Badge, Button, Disclosure, Field, Row, Stack, Textarea } from '../../ui'
import { jsonObjectIssue, noNullIssue, readJsonObject, uuidIssue } from '../../validators/operateRuntime'
import { moveRow } from '../../../shell/documents/documentLogic'
import { formatBp } from '../../../shell/operations/opsLogic'
import { STATUSES as PROPOSAL_STATUSES, canDecide as canApprove, canAcknowledge, canReject as canDecide, canMarkOutcome as canOutcome } from '../../../shell/approvals/approvalLogic'
import { useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { canWrite } from './api/operate'
import { agentRunPath, proposalPath, runPath } from './api/tools'
import type { AgentProposal, AgentRegistry, AgentRun, AgentStats, Outcome } from './api/tools'
import { useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Details, Empty, enumLabel, field, key, optional, Pager, Panel, Pick, Refresh, RuntimeState, selectField, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { FilterForm, JsonDetails, PageSize, ToolsLinks, useListSize } from './components/RuntimeTools'
import { ToolScreen } from './components/ToolScreen'

export default function AgentActionsScreen(props: LiveProps) {
  return <ToolScreen id={props} title={'agentactions'}>{session => <AgentActions session={session} writable={canWrite(props)} />}</ToolScreen>
}

function AgentActions({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const registry = useRuntimeQuery<AgentRegistry>(session, '/ai/agents')
  return <Stack gap={4}>
    <ToolsLinks session={session} sections={['agentssettings', 'agentruns', 'approvals']} />
    <Statistics session={session} />
    <Proposals session={session} writable={writable} registry={registry.data} />
    <RunHistory session={session} />
    <Disclosure label={t(key('agentRegistry'))}>
      {registry.isPending || registry.isError ? <RuntimeState error={registry.error} retry={registry.refetch} /> :
        registry.data.agents.length ? <Stack>
          {registry.data.agents.map(agent => <Disclosure label={data(t, agent.name)} key={agent.name}><Details values={[
            ['stage', data(t, agent.stage)], ['autonomy', enumLabel(t, agent.autonomy)], ['agentActions', data(t, agent.actions.join(', '))],
            ['maxActions', data(t, agent.max_actions_per_run)], ['requiredEval', data(t, agent.require_eval)],
            ['evalReady', agent.eval_ready == null ? data(t, null) : t(key(agent.eval_ready ? 'yes' : 'no'))],
          ]} /></Disclosure>)}
          {registry.data.actions.map(action => <Disclosure label={data(t, action.name)} key={action.name}><Details values={[
            ['description', data(t, action.description)], ['kind', data(t, action.kind)], ['risk', enumLabel(t, action.risk)],
            ['autonomy', enumLabel(t, action.max_autonomy)], ['entity', data(t, action.entity)], ['fields', data(t, action.fields.join(', '))],
          ]} /></Disclosure>)}
          {writable && <StartRun session={session} agents={registry.data.agents} />}
        </Stack> : <Empty message="noAgents" onAction={registry.refetch} />}
    </Disclosure>
  </Stack>
}

function Statistics({ session }: { session: Session }) {
  const t = useT()
  const { search } = useOperateSearch()
  const query = useRuntimeQuery<AgentStats>(session, '/ai/agents/stats', { agent: search.agent })
  return <Panel title={'agentStats'}>
    {query.isPending || query.isError ? <RuntimeState error={query.error} retry={query.refetch} lines={3} /> :
      query.data.agents.length ? <Columns label={'agentStats'} names={['agent', 'runs', 'proposals', 'executed', 'rejected', 'pending', 'worked', 'failedOutcome', 'neutral', 'successRate']}
        rows={query.data.agents.map(row => ({ id: row.agent, cells: [row.agent, row.runs, row.proposals, row.executed, row.rejected, row.pending,
          row.outcome_success, row.outcome_failure, row.outcome_neutral, formatBp(row.success_rate_bp)].map(value => data(t, value)) }))} /> :
        <Empty message="noAgentStats" onAction={query.refetch} />}
  </Panel>
}

function Proposals({ session, writable, registry }: { session: Session; writable: boolean; registry?: AgentRegistry }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const { size, pickSize } = useListSize(20)
  const [focused, setFocused] = useState('')
  const page = search.page ?? 1
  const status = search.status ?? 'pending_approval'
  const list = useRuntimeQuery<Page<AgentProposal>>(session, '/ai/agents/proposals', {
    limit: size, offset: (page - 1) * size, status: status === 'all' ? undefined : status, agent: search.agent, run_id: search.run,
  })
  const selected = useRuntimeQuery<AgentProposal>(session, proposalPath(search.edit ?? ''), {}, Boolean(search.edit))
  const rows = list.data?.items ?? []
  const currentFocus = rows.find(row => row.id === focused)?.id ?? rows[0]?.id
  return <Stack>
    <Panel title={'proposals'}>
      <FilterForm key={JSON.stringify([search.agent, search.run])} fields={[
        field(t, 'agent', { value: search.agent, max: 40, validate: noNullIssue }),
        field(t, 'run', { label: 'runId', value: search.run, max: 36, validate: value => value.trim() ? uuidIssue(value) : undefined }),
      ]} onSubmit={form => change({ agent: optional(form, 'agent'), run: optional(form, 'run'), page: undefined })} />
      <Row><Pick label={t(key('status'))} value={status === 'all' ? '' : status} options={choices(t, PROPOSAL_STATUSES)}
        onChange={status => change({ status: status || 'all', page: undefined })} />
        <PageSize value={size} onChange={pickSize} /><Refresh run={list.refetch} /></Row>
      {list.isPending || list.isError ? <RuntimeState error={list.error} retry={list.refetch} /> :
        rows.length ? <Columns label={'proposals'} names={['proposal', 'risk', 'status', 'autonomy']} rows={rows.map((row, index) => ({
          id: row.id, cells: [
            <Button tabIndex={currentFocus === row.id ? 0 : -1} data-proposal={row.id} aria-expanded={search.edit === row.id}
              onFocus={() => setFocused(row.id)} onClick={() => change({ edit: search.edit === row.id ? undefined : row.id })}
              onKeyDown={event => {
                if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
                event.preventDefault()
                event.currentTarget.closest('table')?.querySelectorAll<HTMLButtonElement>('[data-proposal]')
                  [moveRow(rows.length, index, event.key)]?.focus()
              }}>{t(key('proposalName'), { agent: row.agent, action: row.action })}</Button>,
            <Badge tone={row.risk === 'high' ? 'danger' : row.risk === 'medium' ? 'warning' : 'success'}>{enumLabel(t, row.risk)}</Badge>,
            enumLabel(t, row.status), enumLabel(t, row.allowed_autonomy),
          ],
        }))} /> : <Empty message="noProposals" onAction={list.refetch} />}
      <Pager label={'proposals'} page={page} size={size} total={list.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.edit && <Panel title={'proposalDetail'}>
      <Row><Button onClick={() => change({ edit: undefined })}>{t(key('close'))}</Button></Row>
      {selected.isPending || selected.isError ? <RuntimeState error={selected.error} retry={selected.refetch} /> :
        <Proposal key={selected.data.id} session={session} row={selected.data} writable={writable}
          action={registry?.actions.find(action => action.name === selected.data.action)} />}
    </Panel>}
  </Stack>
}

function Proposal({ session, row, writable, action }: { session: Session; row: AgentProposal; writable: boolean; action?: AgentRegistry['actions'][number] }) {
  const t = useT()
  const date = useOperateDate()
  const [goal, setGoal] = useState(false)
  const run = useRuntimeQuery<AgentRun>(session, runPath(row.run_id), {}, goal)
  return <Stack>
    <Details values={[
      ['agent', data(t, row.agent)], ['action', data(t, row.action)], ['kind', data(t, row.kind)], ['risk', enumLabel(t, row.risk)],
      ['status', enumLabel(t, row.status)], ['autonomy', enumLabel(t, row.allowed_autonomy)],
      ...(action ? [['description', data(t, action.description)], ['entity', data(t, action.entity)], ['fields', data(t, action.fields.join(', '))]] as [string, string][] : []),
    ]} />
    <JsonDetails label={'arguments'} value={row.args} />
    {row.result && <JsonDetails label={'actionResult'} value={row.result} />}
    <Disclosure label={t(key('decisionHistory'))}><Details values={[
      ['reason', data(t, row.reason)], ['errorCode', data(t, row.error_code)], ['handoffRole', data(t, row.handoff_role)],
      ['executedBy', data(t, row.executed_by)], ['decidedBy', data(t, row.decided_by)], ['decidedAt', date(row.decided_at)],
      ['decisionNote', data(t, row.note)], ['outcome', row.outcome ? enumLabel(t, row.outcome) : data(t, null)],
      ['outcomeBy', data(t, row.outcome_by)], ['outcomeAt', date(row.outcome_at)], ['created', date(row.created_at)],
    ]} /></Disclosure>
    <Row><Button aria-expanded={goal} onClick={() => setGoal(!goal)}>{t(key('runGoal'))}</Button></Row>
    {goal && (run.isPending || run.isError ? <RuntimeState error={run.error} retry={run.refetch} /> : <RunDetail run={run.data} />)}
    {writable && <ProposalActions session={session} row={row} />}
  </Stack>
}

type Decision = 'approve' | 'acknowledge' | 'reject' | 'handoff' | 'outcome'
type DecisionBody = { note?: string; reason?: string; to_role?: string; outcome?: Outcome } | undefined
function ProposalActions({ session, row }: { session: Session; row: AgentProposal }) {
  const t = useT()
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const actions = [
    ...(canApprove(row.status) ? ['approve'] : []), ...(canAcknowledge(row.status) ? ['acknowledge'] : []),
    ...(canDecide(row.status) ? ['reject', 'handoff'] : []), ...(canOutcome(row) ? ['outcome'] : []),
  ] as Decision[]
  return <Stack>
    {actions.some(action => action !== 'reject' && action !== 'acknowledge') && <Field label={t(key('decisionNote'))}
      error={note.includes('\0') ? t(key('nullCharacter')) : undefined}>
      {attrs => <Textarea {...attrs} value={note} maxLength={500} onChange={event => setNote(event.target.value)} />}
    </Field>}
    {actions.map(action => <ProposalDecision key={action} action={action} session={session} row={row} note={note} reason={reason} setReason={setReason} />)}
  </Stack>
}

function ProposalDecision({ action, session, row, note, reason, setReason }: {
  action: Decision; session: Session; row: AgentProposal; note: string; reason: string; setReason: (value: string) => void
}) {
  const t = useT()
  const request = useRuntimeWrite<DecisionBody, AgentProposal>(session, `${proposalPath(row.id)}/${action}`)
  const body = { note: note.trim() || undefined }
  const label = t(key(action))
  if (action === 'handoff') return <Disclosure label={label}><Stack>
    <Form fields={[field(t, 'to_role', { label: 'handoffRole', max: 40, required: true, validate: noNullIssue })]}
      submitLabel={t(key('handoffConfirm'))} submitProps={{ disabled: note.includes('\0') }} pending={request.isPending} serverErrors={serverFields(request.error)}
      onSubmit={form => request.mutate({ ...body, to_role: text(form, 'to_role') })} />
    <WriteStatus error={request.error} reload={request.reset} />
  </Stack></Disclosure>
  return <Stack>
    <Row>{action === 'reject' || action === 'approve' ?
      <ConfirmDestructive trigger={<Button variant={action === 'reject' ? 'danger' : 'default'}>{label}</Button>}
        title={label} description={t(key(action === 'reject' ? 'rejectProposalHelp' : 'approveProposalHelp'))} action={label}
        pending={request.isPending} disabled={reason.includes('\0') || note.includes('\0')} onConfirm={async () => {
          await request.mutateAsync(action === 'reject' ? { reason: reason.trim() || undefined } : body)
        }}>
        {action === 'reject' && <Field label={t(key('optionalReason'))} error={reason.includes('\0') ? t(key('nullCharacter')) : undefined}>
          {attrs => <Textarea {...attrs} maxLength={500} value={reason} onChange={event => setReason(event.target.value)} />}
        </Field>}
      </ConfirmDestructive> : action === 'outcome' ?
        (['success', 'failure', 'neutral'] as const).map((outcome, index) =>
          <Button key={outcome} disabled={request.isPending || note.includes('\0')} onClick={() => request.mutate({ ...body, outcome })}>
            {t(key(['worked', 'failedOutcome', 'neutral'][index]))}
          </Button>) : <Button disabled={request.isPending} onClick={() => request.mutate(undefined)}>{label}</Button>}</Row>
    <WriteStatus error={request.error} reload={request.reset} />
  </Stack>
}

function RunHistory({ session }: { session: Session }) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const page = search.historyPage ?? 1
  const list = useRuntimeQuery<Page<AgentRun>>(session, '/ai/agents/runs', { limit: 20, offset: (page - 1) * 20, agent: search.owner, status: search.view })
  const detail = useRuntimeQuery<AgentRun>(session, runPath(search.report ?? ''), {}, Boolean(search.report))
  return <Disclosure label={t(key('runHistory'))}><Stack>
    <FilterForm key={search.owner} fields={[field(t, 'agent', { value: search.owner, max: 40, validate: noNullIssue })]}
      onSubmit={form => change({ owner: optional(form, 'agent'), historyPage: undefined })} />
    <Row><Pick label={t(key('runStatus'))} value={search.view ?? ''} options={choices(t, ['completed', 'failed', 'refused'])}
      onChange={view => change({ view: view || undefined, historyPage: undefined })} /><Refresh run={list.refetch} /></Row>
    {list.isPending || list.isError ? <RuntimeState error={list.error} retry={list.refetch} /> :
      list.data.items.length ? <Columns label={'runHistory'} names={['agent', 'goal', 'status', 'created']} rows={list.data.items.map(row => ({
        id: row.id, cells: [data(t, row.agent), <Button onClick={() => change({ report: search.report === row.id ? undefined : row.id })}>{data(t, row.goal)}</Button>,
          enumLabel(t, row.status), date(row.created_at)],
      }))} /> : <Empty message="noRuns" onAction={list.refetch} />}
    <Pager label={'runHistory'} page={page} size={20} total={list.data?.total ?? 0} change={historyPage => change({ historyPage })} />
    {search.report && (detail.isPending || detail.isError ? <RuntimeState error={detail.error} retry={detail.refetch} /> : <RunDetail run={detail.data} />)}
  </Stack></Disclosure>
}

function RunDetail({ run }: { run: AgentRun }) {
  const t = useT()
  const date = useOperateDate()
  return <Stack><Details values={[
    ['runId', data(t, run.id)], ['agent', data(t, run.agent)], ['goal', data(t, run.goal)], ['mode', enumLabel(t, run.mode)],
    ['effectiveAutonomy', enumLabel(t, run.effective_autonomy)], ['status', enumLabel(t, run.status)], ['errorCode', data(t, run.error_code)],
    ['callId', data(t, run.call_id)], ['startedBy', data(t, run.started_by)], ['created', date(run.created_at)],
  ]} />{run.proposals.length > 0 && <JsonDetails label={'proposals'} value={run.proposals} />}</Stack>
}

function StartRun({ session, agents }: { session: Session; agents: AgentRegistry['agents'] }) {
  const t = useT()
  const [agent, setAgent] = useState(agents[0]?.name ?? '')
  const request = useRuntimeWrite<{ goal: string; context?: Record<string, unknown>; mode?: string; idempotency_key?: string }, AgentRun>(session, agentRunPath(agent))
  return <Disclosure label={t(key('startRun'))}><Stack>
    <Pick label={t(key('agent'))} value={agent} options={agents.map(agent => ({ value: agent.name, label: data(t, agent.name) }))} onChange={setAgent} />
    <Form fields={[
      field(t, 'goal', { max: 4000, area: true, required: true, validate: noNullIssue }),
      selectField(t, 'mode', [{ value: 'default', label: t(key('agentDefault')) }, ...choices(t, ['suggest', 'draft', 'auto']).slice(1)], 'default'),
      field(t, 'context', { area: true, validate: value => {
        if (!value.trim()) return
        return jsonObjectIssue(value) ?? (new TextEncoder().encode(value).length > 8192 ? { key: key('contextLimit') } : undefined)
      } }),
      field(t, 'idempotency_key', { label: 'idempotencyKey', max: 128, validate: noNullIssue }),
    ]} pending={request.isPending} submitLabel={t(key('startRun'))} serverErrors={serverFields(request.error)}
      onSubmit={form => request.mutate({
        goal: text(form, 'goal'), mode: text(form, 'mode') === 'default' ? undefined : text(form, 'mode'),
        context: readJsonObject(text(form, 'context')), idempotency_key: optional(form, 'idempotency_key'),
      })} />
    <WriteStatus error={request.error} reload={request.reset} success={request.data ? t(key('runStarted')) : undefined} />
    {request.data && <RunDetail run={request.data.data} />}
  </Stack></Disclosure>
}
