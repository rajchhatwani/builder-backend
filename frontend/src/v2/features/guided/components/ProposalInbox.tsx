import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import {
  canAcknowledge, canDecide, canHandOff, canMarkOutcome, canReject, isStatus, OUTCOMES, STATUSES,
} from '../../../../shell/approvals/approvalLogic'
import type { AgentStat, Proposal, Run } from '../../../../shell/approvals/approvalLogic'
import { redactJson } from '../../../../shell/workbench/workbenchLogic'
import { isReady } from '../../../../shell/ai/seeItLogic'
import { useT } from '../../../i18n'
import { Form, SettingsSection } from '../../../patterns'
import { Alert, Badge, Button, Card, CodeBlock, Dialog, EmptyState, Field, Input, Pagination, Row, Select, Skeleton, Stack } from '../../../ui'
import { deliveryLimits, guidedLimits, isUuid, validators } from '../../../validators'
import { previewsOptions } from '../api/delivery'
import type { Preview } from '../api/delivery'
import { previewJson, previewKeys } from '../api/preview'
import type { Credential } from '../state/preview'
import { ConfirmAction, DeliveryError, ProjectLink } from './DeliveryControls'
import { GuidedLoadError } from './GuidedFeedback'
import { usePreviewCredentials } from './PreviewCredentials'
import { PreviewIdentity } from './PreviewIdentity'

const route = '/projects/$projectId/$section'
const prefix = '/ai/agents'
type Connection = { preview: Preview; credential: Credential }
type ProposalPage = { items: Proposal[]; total: number }
type Outcome = typeof OUTCOMES[number]

export function ProposalInbox({ projectId, write }: { projectId: string; write: boolean }) {
  const t = useT()
  const previews = useQuery(previewsOptions(projectId))
  const { credentials } = usePreviewCredentials()
  const available = previews.data?.filter(item => !item.workspace_id && isReady(item.state) && credentials[item.id]) ?? []
  const active = available.find(item => credentials[item.id]?.bearer) ?? available[0]
  const credential = active ? credentials[active.id] : undefined
  return <SettingsSection title={t('approval.proposals')} description={t('proposal.intro')}>
    {previews.isPending ? <Skeleton label={t('preview.loading')} />
      : previews.isError ? <GuidedLoadError error={previews.error} label={t('preview.loadError')} retry={() => void previews.refetch()} />
      : active && credential ? <>
        <PreviewIdentity preview={active} credential={credential} allowRegister={write} />
        {credential.bearer ? <ProposalList key={active.id + ':' + credential.revision} preview={active} credential={credential} write={write} />
          : <p>{t('proposal.signIn')}</p>}
      </> : <EmptyState title={t('proposal.noPreview')}
        action={<ProjectLink projectId={projectId} section="see">{t('nav.see')}</ProjectLink>} />}
  </SettingsSection>
}

function ProposalList({ preview, credential, write }: Connection & { write: boolean }) {
  const t = useT()
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const status = search.decision && isStatus(search.decision) ? search.decision : STATUSES[0]
  const page = search.page ?? 1
  const key = [...previewKeys.proxy(preview.id, credential.revision), 'proposals']
  const listParams = new URLSearchParams({ status, limit: '20', offset: String((page - 1) * 20) })
  if (search.entity) listParams.set('agent', search.entity)
  if (search.run && isUuid(search.run)) listParams.set('run_id', search.run)
  const list = useQuery({
    queryKey: [...key, 'list', listParams.toString()], retry: false, gcTime: 0,
    queryFn: () => previewJson<ProposalPage>(preview, credential, prefix + '/proposals?' + listParams),
  })
  const stats = useQuery({
    queryKey: [...key, 'stats', search.entity], retry: false, gcTime: 0,
    queryFn: () => previewJson<{ agents: AgentStat[] }>(preview, credential, prefix + '/stats' + (search.entity ? '?agent=' + encodeURIComponent(search.entity) : '')),
  })
  return <Stack>
    <Row>
      <Field label={t('approval.columns.status')}>{attrs => <Select triggerProps={attrs} value={status}
        options={STATUSES.map(value => ({ value, label: t('proposal.status.' + value) }))}
        onValueChange={decision => void navigate({ search: previous => ({ ...previous, decision, page: undefined }) })} />}</Field>
      <Field label={t('proposal.agent')}>{attrs => <Input {...attrs} value={search.entity ?? ''} maxLength={deliveryLimits.proposalRole} onChange={event => {
        const entity = event.target.value || undefined
        void navigate({ search: previous => ({ ...previous, entity, page: undefined }), replace: true })
      }} />}</Field>
      <Field label={t('approval.filters.run')}>{attrs => <Input {...attrs} value={search.run ?? ''} onChange={event => {
        const run = event.target.value || undefined
        void navigate({ search: previous => ({ ...previous, run, page: undefined }), replace: true })
      }} />}</Field>
      <Button onClick={() => { void list.refetch(); void stats.refetch() }}>{t('approval.refresh')}</Button>
    </Row>
    {status === 'rejected_by_policy' && <Alert>{t('proposal.policy')}</Alert>}
    {stats.isPending && <Skeleton />}
    {stats.isError && <GuidedLoadError error={stats.error} label={t('proposal.statsError')} retry={() => void stats.refetch()} />}
    {stats.data?.agents.map(agent => <Card key={agent.agent}><Stack gap={1}>
      <strong>{agent.agent}</strong>
      <p>{t('proposal.stats', { runs: agent.runs, proposals: agent.proposals, executed: agent.executed, rejected: agent.rejected, pending: agent.pending })}</p>
      <p>{t('proposal.outcomes', { success: agent.outcome_success, failure: agent.outcome_failure, neutral: agent.outcome_neutral })}</p>
      {agent.success_rate_bp != null && <p>{t('proposal.successRate', { rate: new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 2 }).format(agent.success_rate_bp / 10_000) })}</p>}
    </Stack></Card>)}
    {list.isPending ? <Skeleton label={t('proposal.loading')} lines={5} />
      : list.isError ? <GuidedLoadError error={list.error} label={t('proposal.loadError')} retry={() => void list.refetch()} />
      : <>
        {!list.data.items.length && <EmptyState title={t('proposal.empty')}
          action={<Button onClick={() => void list.refetch()}>{t('approval.refresh')}</Button>} />}
        {list.data.items.filter(item => !search.run || item.run_id.includes(search.run)).map(item => <ProposalCard key={item.id} preview={preview} credential={credential} item={item} write={write} />)}
        <Pagination label={t('approval.proposals')} page={page} pages={Math.ceil(list.data.total / 20)}
          onChange={page => void navigate({ search: previous => ({ ...previous, page }) })} />
      </>}
  </Stack>
}

type Operation =
  | { kind: 'acknowledge' }
  | { kind: 'approve' | 'reject'; text: string }
  | { kind: 'handoff'; role: string; text: string }
  | { kind: 'outcome'; outcome: Outcome; text: string }

function ProposalCard({ preview, credential, item, write }: Connection & { item: Proposal; write: boolean }) {
  const t = useT()
  const client = useQueryClient()
  const [showGoal, setShowGoal] = useState(false)
  const key = [...previewKeys.proxy(preview.id, credential.revision), 'proposals']
  const goal = useQuery({
    queryKey: [...key, 'run', item.run_id], enabled: showGoal, retry: false, gcTime: 0,
    queryFn: () => previewJson<Run>(preview, credential, prefix + '/runs/' + encodeURIComponent(item.run_id)),
  })
  const change = useMutation({
    mutationFn: (operation: Operation) => {
      const path = prefix + '/proposals/' + encodeURIComponent(item.id) + '/' + operation.kind
      switch (operation.kind) {
        case 'approve': return previewJson<Proposal>(preview, credential, path, 'POST', { note: operation.text || null })
        case 'reject': return previewJson<Proposal>(preview, credential, path, 'POST', { reason: operation.text || null })
        case 'acknowledge': return previewJson<Proposal>(preview, credential, path, 'POST')
        case 'handoff': return previewJson<Proposal>(preview, credential, path, 'POST', { to_role: operation.role, note: operation.text || null })
        case 'outcome': return previewJson<Proposal>(preview, credential, path, 'POST', { outcome: operation.outcome, note: operation.text || null })
      }
    },
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  })
  const submit = async (operation: Operation) => { await change.mutateAsync(operation) }
  return <Card><Stack>
    <Row><h3>{item.action}</h3><Badge>{t('proposal.status.' + item.status)}</Badge>
      <Badge tone={item.risk === 'high' ? 'danger' : 'neutral'}>{t('proposal.risk', { risk: item.risk })}</Badge></Row>
    <p>{t('proposal.details', { agent: item.agent, autonomy: item.allowed_autonomy })}</p>
    {item.reason && <p>{item.reason}</p>}
    {item.note && <p>{item.note}</p>}
    {item.error_code && <Alert tone="danger">{item.error_code}</Alert>}
    {item.outcome && <Badge>{t('proposal.outcome.' + item.outcome)}</Badge>}
    <details><summary>{t('proposal.arguments')}</summary><CodeBlock code={JSON.stringify(redactJson(item.args), null, 2)} /></details>
    {item.result && <details><summary>{t('proposal.result')}</summary><CodeBlock code={JSON.stringify(redactJson(item.result), null, 2)} /></details>}
    <Row><Button aria-expanded={showGoal} onClick={() => setShowGoal(!showGoal)}>{t('proposal.goal')}</Button></Row>
    {showGoal && (goal.isPending ? <Skeleton /> : goal.isError ? <GuidedLoadError error={goal.error} label={t('proposal.loadError')} retry={() => void goal.refetch()} />
      : <p>{goal.data.goal}</p>)}
    <DeliveryError error={change.error} reload={() => { change.reset(); void client.invalidateQueries({ queryKey: key }) }} />
    {write && <Row>
      {canDecide(item.status) && <ProposalForm kind="approve" submit={submit} pending={change.isPending} />}
      {canAcknowledge(item.status) && <Button disabled={change.isPending} onClick={() => change.mutate({ kind: 'acknowledge' })}>{t('proposal.actions.acknowledge')}</Button>}
      {canReject(item.status) && <ProposalForm kind="reject" submit={submit} pending={change.isPending} />}
      {canHandOff(item.status) && <ProposalForm kind="handoff" submit={submit} pending={change.isPending} />}
      {canMarkOutcome(item) && OUTCOMES.map(outcome => <ProposalForm key={outcome} kind="outcome" outcome={outcome} submit={submit} pending={change.isPending} />)}
    </Row>}
  </Stack></Card>
}

function ProposalForm({ kind, outcome, submit, pending }: {
  kind: 'approve' | 'reject' | 'handoff' | 'outcome'; outcome?: Outcome; submit: (operation: Operation) => Promise<void>; pending: boolean
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [failed, setFailed] = useState(false)
  const label = t(outcome ? 'proposal.outcome.' + outcome : 'proposal.actions.' + kind)
  const [text, setText] = useState('')
  if (kind === 'approve') return <Stack gap={1}>
    <Field label={t('proposal.note')}>{attrs => <Input {...attrs} maxLength={guidedLimits.note} value={text} onChange={event => setText(event.target.value)} />}</Field>
    <ConfirmAction label={label} title={t('proposal.approveTitle')} description={t('proposal.approveBody')} pending={pending}
      onConfirm={() => submit({ kind, text: text.trim() })} />
  </Stack>

  return <Dialog title={label} open={open} onOpenChange={value => { setOpen(value); setFailed(false) }} trigger={<Button disabled={pending}>{label}</Button>}>
    <Form submitLabel={t('approval.confirm')} pending={pending} formError={failed ? t('common.actionFailed') : undefined}
      fields={[
        ...(kind === 'handoff' ? [{ name: 'role', label: t('proposal.role'),
          validate: [validators.required, validators.length(deliveryLimits.proposalRole)], control: (attrs: Parameters<typeof Input>[0]) => <Input {...attrs} /> }] : []),
        { name: 'note', label: t(kind === 'reject' ? 'proposal.reason' : 'proposal.note'),
          validate: [validators.length(guidedLimits.note)], control: attrs => <Input {...attrs} /> },
      ]} onSubmit={async data => {
        const text = String(data.get('note')).trim()
        try {
          if (kind === 'handoff') await submit({ kind, role: String(data.get('role')).trim(), text })
          else if (kind === 'outcome' && outcome) await submit({ kind, outcome, text })
          else if (kind === 'reject') await submit({ kind, text })
          setOpen(false)
        } catch { setFailed(true) }
      }} />
  </Dialog>
}
