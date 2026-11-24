import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { useRef, useState } from 'react'
import { confirmMatches, describePayload, effectiveState, gateDInfo, KIND_LABEL, RISK_LABEL } from '../../../shell/ai/approvalLogic'
import { useT } from '../../i18n'
import { ConflictBanner, PageHeader, ReadOnlyNote, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Card, CodeBlock, EmptyState, Field, Input, Row, Select, Skeleton, Stack, Table, Tabs, Textarea } from '../../ui'
import { guidedLimits, isUuid, validators } from '../../validators'
import { inboxOptions, reviewOptions, runOptions, useApprovalDecision, useRunAction } from './api/delivery'
import type { Approval } from './api/delivery'
import { errorCode, errorStatus, useGuidedAccess } from './api/guided'
import { ApprovalLink, ConfirmAction, DeliveryError, ProjectLink } from './components/DeliveryControls'
import { GuidedLoadError } from './components/GuidedFeedback'
import { formatGuidedDate } from './components/WorkspacePanel'
import { ProposalInbox } from './components/ProposalInbox'
import './guided.css'

const route = '/projects/$projectId/$section'
const closed = ['approved', 'denied', 'expired', 'superseded']
const tabs = ['pending', 'decided', 'proposals']

export default function ApprovalsScreen() {
  const t = useT()
  const { projectId } = useParams({ from: route })
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const access = useGuidedAccess(projectId)
  const write = access.role === 'owner' || access.role === 'editor'
  const selected = tabs.includes(search.tab ?? '') ? search.tab! : 'pending'
  return <Stack gap={5} data-testid="approvals-page">
    <PageHeader title={t('nav.approvals')} description={t('approval.intro')} />
    {access.failed && <GuidedLoadError error={access.account.error ?? access.members.error} retry={access.retry} label={t('guided.accessError')} />}
    {!access.failed && !access.pending && !write && <ReadOnlyNote>{t('approval.viewer')}</ReadOnlyNote>}
    {search.approval ? <ApprovalReview key={search.approval} approvalId={search.approval} projectId={projectId} role={access.role}
      verified={access.verified} reviewer={id => access.members.data?.find(member => member.user_id === id)?.name} />
      : <Tabs label={t('approval.inbox')} value={selected}
        onChange={tab => void navigate({ search: previous => ({ ...previous, tab, page: undefined }) })}
        items={tabs.map(id => ({
          id, label: t('approval.' + id),
          content: selected === id ? id === 'proposals' ? <ProposalInbox projectId={projectId} write={write} />
            : <ApprovalList projectId={projectId} waiting={id === 'pending'} /> : null,
        }))} />}
  </Stack>
}

function ApprovalList({ projectId, waiting }: { projectId: string; waiting: boolean }) {
  const t = useT()
  const search = useSearch({ from: route })
  const navigate = useNavigate({ from: route })
  const states = waiting ? ['pending'] : search.decision && closed.includes(search.decision) ? [search.decision] : closed
  const approvals = useQuery(inboxOptions(projectId, states, search.run && isUuid(search.run) ? search.run : undefined))
  const rows = approvals.data?.rows.filter(row =>
    (!search.kind || row.kind === search.kind) && (!search.risk || row.risk_flags.includes(search.risk))
    && (!search.run || row.run_id.toLowerCase().includes(search.run.toLowerCase())) && (!search.owner || row.requires_owner) && (waiting ? effectiveState(row) === 'pending' : true),
  ) ?? []
  function filter(key: 'kind' | 'risk' | 'decision' | 'owner' | 'run', value: string) {
    void navigate({ search: previous => ({ ...previous, [key]: value === 'all' ? undefined : value || undefined }), replace: key === 'run' })
  }
  const filters: { key: 'kind' | 'risk' | 'owner' | 'decision'; values: string[]; labels: string }[] = [
    { key: 'kind', values: Object.keys(KIND_LABEL), labels: 'approval.kinds.' },
    { key: 'risk', values: Object.keys(RISK_LABEL), labels: 'approval.risks.' },
    { key: 'owner', values: ['owner'], labels: 'approval.' },
    
  ]
  if (!waiting) filters.push({ key: 'decision', values: closed, labels: 'approval.states.' })
  return <SettingsSection title={t(waiting ? 'approval.pending' : 'approval.decided')}>
    <Row>
      {filters.map(({ key, values, labels }) => <Field key={key} label={t('approval.filters.' + key)}>{attrs =>
        <Select triggerProps={attrs} value={values.some(value => value === search[key]) ? search[key] : 'all'}
          options={[{ value: 'all', label: t('approval.filters.all_' + key) }, ...values.map(value => ({ value, label: t(labels + value) }))]}
          onValueChange={value => filter(key, value)} />}
      </Field>)}
      <Field label={t('approval.filters.run')}>{attrs => <Input {...attrs} value={search.run ?? ''}
        onChange={event => filter('run', event.target.value)} />}</Field>
      <Button onClick={() => void approvals.refetch()} disabled={approvals.isFetching}>{t('approval.refresh')}</Button>
    </Row>
    {approvals.isPending ? <Skeleton lines={8} label={t('approval.loading')} />
      : approvals.isError ? <GuidedLoadError error={approvals.error} label={t('approval.loadError')} retry={() => void approvals.refetch()} />
      : rows.length === 0 ? <EmptyState title={t(waiting ? 'approval.empty' : 'approval.noDecisions')}
        action={<ProjectLink projectId={projectId} section="build">{t('approval.backBuild')}</ProjectLink>} />
      : <Table label={t('approval.inbox')} columns={['request', 'gate', 'status', 'run'].map(id => ({ id, label: t('approval.columns.' + id) }))}
        rows={rows.map(row => ({ id: row.id, cells: [
          <ApprovalLink projectId={projectId} approval={row} />,
          <Row><Badge>{t('approval.kind', { kind: row.kind, name: t('approval.kinds.' + row.kind) })}</Badge>{row.requires_owner && <Badge tone="warning">{t('approval.owner')}</Badge>}</Row>,
          <Stack gap={1}><Badge>{t('approval.states.' + effectiveState(row))}</Badge>{waiting && <span>{t('approval.expires', { date: formatGuidedDate(row.expires_at) })}</span>}</Stack>,
          <RunLink projectId={projectId} run={row.run_id} />,
        ] }))} />}
    {approvals.data?.capped && <p>{t('approval.capped')}</p>}
  </SettingsSection>
}

function RunLink({ projectId, run }: { projectId: string; run: string }) {
  const t = useT()
  return <ProjectLink projectId={projectId} section="build" search={{ run }}>{t('approval.run', { run: run.slice(0, 8) })}</ProjectLink>
}

function ApprovalReview({ projectId, approvalId, role, verified, reviewer }: {
  projectId: string; approvalId: string; role?: string; verified: boolean; reviewer: (id: string) => string | undefined
}) {
  const t = useT()
  const query = useQuery(reviewOptions(projectId, approvalId))
  const item = query.data
  return <Stack>
    <Row>
      <ProjectLink projectId={projectId} section="approvals">{t('approval.back')}</ProjectLink>
      {item && <RunLink projectId={projectId} run={item.run_id} />}
    </Row>
    {query.isPending ? <Card><Skeleton lines={8} label={t('approval.loading')} /></Card>
      : query.isError ? <GuidedLoadError error={query.error} label={t('approval.loadError')} retry={() => void query.refetch()} />
      : item?.kind === 'A' ? <EmptyState title={t('approval.planOwnPage')}
        action={<ApprovalLink projectId={projectId} approval={item} />} />
      : item && <DecisionCard projectId={projectId} item={item} role={role} verified={verified} reviewer={reviewer}
        reload={() => void query.refetch()} />}
  </Stack>
}

function DecisionCard({ projectId, item, role, verified, reviewer, reload }: {
  projectId: string; item: Approval; role?: string; verified: boolean; reviewer: (id: string) => string | undefined; reload: () => void
}) {
  const t = useT()
  const decision = useApprovalDecision(projectId, item.id)
  const resume = useRunAction(projectId, item.run_id)
  const state = effectiveState(item)
  const detail = describePayload(item.payload)
  const phrase = item.kind === 'D' ? gateDInfo(item.payload).phrase : undefined
  const [note, setNote] = useState('')
  const [typed, setTyped] = useState('')
  const [denying, setDenying] = useState(false)
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const length = validators.length(guidedLimits.note)(note)
  const noteIssue = length ?? (denying ? validators.required(note) : undefined)
  const conflict = decision.data?.changed || errorStatus(decision.error) === 409
  const canEdit = role === 'owner' || role === 'editor'
  const forbidden = errorStatus(decision.error) === 403
  const canDecide = state === 'pending' && canEdit && (!item.requires_owner || role === 'owner') && !conflict && !forbidden
  const run = useQuery({ ...runOptions(projectId, item.run_id), enabled: detail.files.length > 0 || (state === 'approved' && canEdit && verified) })
  const send = (approve: boolean) => decision.mutateAsync({ seen: item, approve, note: note.trim() })
  const workspace = run.data?.workspace_id
  const resumable = run.data && ['created', 'planning', 'running', 'awaiting_approval', 'stopped'].includes(run.data.state)
    && (run.data.stop_code !== 'apply_conflict' || role === 'owner')

  return <SettingsSection title={item.subject} description={t('approval.intros.' + item.kind)}>
    <Row><Badge>{t('approval.kind', { kind: item.kind, name: t('approval.kinds.' + item.kind) })}</Badge>
      {item.requires_owner && <Badge tone="warning">{t('approval.owner')}</Badge>}
      <Badge>{t('approval.states.' + state)}</Badge><span>{t('approval.expires', { date: formatGuidedDate(item.expires_at) })}</span>
    </Row>
    {conflict && <ConflictBanner onReload={() => { decision.reset(); reload(); setTyped('') }}>{t('approval.changed')}</ConflictBanner>}
    {!conflict && <DeliveryError error={decision.error} reload={reload} />}
    {state === 'expired' && <Alert tone="warning">{t('approval.expired')}</Alert>}
    {state === 'superseded' && <Alert tone="warning">{t('approval.superseded')}</Alert>}
    {state === 'pending' && item.requires_owner && canEdit && role !== 'owner' && <ReadOnlyNote>{t('approval.ownerOnly')}</ReadOnlyNote>}
    <Row>{item.risk_flags.length ? item.risk_flags.map(flag => <Badge key={flag} tone="warning">{flag in RISK_LABEL ? t('approval.risks.' + flag) : flag}</Badge>)
      : <p>{t('approval.noRisk')}</p>}</Row>
    {detail.summary && <p>{detail.summary}</p>}
    {(detail.diffRows.length > 0 || detail.specDiff.length > 0) && <SettingsSection title={t('approval.specChanges')}>
      {detail.diffRows.length > 0 && <Table label={t('approval.specChanges')}
        columns={['section', 'added', 'removed', 'changed'].map(id => ({ id, label: t('approval.columns.' + id) }))}
        rows={detail.diffRows.map((row, index) => ({ id: String(index), cells: [row.section, row.added.join(', '), row.removed.join(', '), row.changed.join(', ')] }))} />}
      <details><summary>{t('approval.rawDiff')}</summary><CodeBlock code={JSON.stringify(item.payload.spec_diff ?? item.payload.diff, null, 2)} /></details>
    </SettingsSection>}
    {(detail.hooks.length > 0 || detail.hasAiCode) && <SettingsSection title={t('approval.hooks')}>
      {detail.hasAiCode && <Alert>{t('approval.aiCode')}</Alert>}
      {detail.hooks.map((hook, index) => <Row key={index}><strong>{hook.name}</strong><Badge>{hook.author}</Badge></Row>)}
    </SettingsSection>}
    {detail.files.length > 0 && <SettingsSection title={t('approval.files', { count: detail.files.length })}>
      {run.isPending && <Skeleton />}
      {run.isError && <GuidedLoadError error={run.error} label={t('build.loadError')} retry={() => void run.refetch()} />}
      {detail.files.map((file, index) => workspace
        ? <Row key={index}><ProjectLink projectId={projectId} section="code" search={{ run: item.run_id, workspace, file }}>{file}</ProjectLink></Row>
        : <p key={index}>{file}</p>)}
    </SettingsSection>}
    {item.kind === 'C' && <p>{detail.gateHash ? t('approval.gateReport', { hash: detail.gateHash }) : t('approval.noReport')}</p>}
    {item.kind === 'D' && <SettingsSection title={t('approval.whatChanges')}>
      <p>{item.subject}</p><p>{t('approval.separationHint')}</p>
    </SettingsSection>}
    {detail.facts.length > 0 && <dl>{detail.facts.map(({ key, value }) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>}
    {!detail.summary && !detail.facts.length && !detail.diffRows.length && !detail.specDiff.length && !detail.hooks.length && !detail.files.length && !phrase && <p>{t('approval.noDetails')}</p>}
    {item.decided_by && <p>{t('approval.decidedBy', { name: reviewer(item.decided_by) ?? item.decided_by, date: formatGuidedDate(item.decided_at) })}</p>}
    {item.decision_note && <p>{t('approval.noteValue', { note: item.decision_note })}</p>}
    {item.bound_spec_hash && <p>{t('approval.boundSpec', { hash: item.bound_spec_hash })}</p>}
    {item.bound_commit && <p>{t('approval.boundCommit', { hash: item.bound_commit })}</p>}
    {canDecide && <>
      <Field label={t('approval.note')} hint={t('approval.noteHint')} error={noteIssue ? t(noteIssue.key, noteIssue.values) : undefined}>
        {attrs => <Textarea {...attrs} ref={noteRef} value={note} onChange={event => setNote(event.target.value)} />}
      </Field>
      {phrase && <Field label={t('approval.phrase', { phrase })}>{attrs => <Input {...attrs} value={typed} onChange={event => setTyped(event.target.value)} />}</Field>}
      <Row>
        <ConfirmAction label={t('approval.approve')} title={t('approval.confirmTitle')}
          description={t(item.kind === 'C' ? 'approval.confirmCode' : 'approval.confirmBody')}
          destructive={item.kind === 'D' || item.kind === 'E'} disabled={Boolean(length || phrase && !confirmMatches(typed, phrase))}
          pending={decision.isPending} onConfirm={async () => {
            if (length || phrase && !confirmMatches(typed, phrase)) return
            await send(true)
          }} testId="review-approve" />
        <Button disabled={decision.isPending} data-testid="review-deny" onClick={() => {
          setDenying(true)
          if (length || !note.trim()) noteRef.current?.focus()
          else void send(false).catch(() => undefined)
        }}>{t('approval.deny')}</Button>
      </Row>
    </>}
    {state === 'approved' && <Alert tone="success">{t('approval.approved')}</Alert>}
    {state === 'denied' && <Alert>{t('approval.denied')}</Alert>}
    {state !== 'pending' && <Row>
      <ProjectLink projectId={projectId} section="build" search={{ run: item.run_id }}>{t('approval.backBuild')}</ProjectLink>
      {state === 'approved' && canEdit && verified && resumable && <Button variant="primary" disabled={resume.isPending}
        onClick={() => resume.mutate('resume')}>{t('approval.resume')}</Button>}
    </Row>}
    {resume.isSuccess && <Alert tone="success">{t('approval.resumed')}</Alert>}
    <DeliveryError error={resume.error} reload={() => { resume.reset(); if (errorCode(resume.error)) void run.refetch() }} />
  </SettingsSection>
}
