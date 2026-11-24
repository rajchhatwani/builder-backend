import { useReducer, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useLanguage, useT } from '../../../i18n'
import { ConfirmDestructive, Form, ListRow, ReadOnlyNote } from '../../../patterns'
import { Alert, Badge, Button, Card, Field, Input, Row, Select, Stack, Table, Textarea } from '../../../ui'
import { guidedLimits, planNameChecks, validators } from '../../../validators'
import type { Approval } from '../api/guided'
import { buildScope, extensionRows, planReducer, rowKey, scopeKinds, scopeRows } from '../state/plan'
import type { ScopeKind, ScopeRow } from '../state/plan'
import '../guided.css'

function ReviewScope({ rows, editable, busy, onToggle }: {
  rows: ScopeRow[]; editable?: boolean; busy?: boolean; onToggle?: (row: ScopeRow) => void
}) {
  const t = useT()
  return !rows.length ? <p>{t('plan.noScope')}</p> : <Table label={t('plan.scope')} columns={[
    { id: 'kind', label: t('plan.kind') }, { id: 'name', label: t('plan.mayTouch') },
    ...(editable ? [{ id: 'action', label: t('plan.action') }] : []),
  ]} rows={rows.map(row => ({ id: rowKey(row), cells: [
    t(`plan.kinds.${row.kind}`),
    <span className={row.removed ? 'v2-scope-removed' : undefined}>{t('common.serverText', { text: row.name })}</span>,
    ...(editable ? [<Button disabled={busy} aria-label={t(row.removed ? 'plan.keepName' : 'plan.removeName', { name: row.name, kind: t(`plan.kinds.${row.kind}`) })}
      onClick={() => onToggle?.(row)}>{t(row.removed ? 'plan.keep' : 'plan.remove')}</Button>] : []),
  ] }))} />
}

const knownRisks = ['auth', 'tenancy', 'money', 'public_endpoints', 'data_deletion', 'new_egress', 'new_dependencies']
const knownStates = ['approved', 'denied', 'expired', 'superseded']

export function PlanReview({ approval, owner, editor, checking, busy, blocked, reviewer, onDecision, error, noteError, links }: {
  approval: Approval; owner: boolean; editor: boolean; checking: boolean; busy: boolean; blocked: boolean; reviewer?: string;
  onDecision: (approve: boolean, note: string, plan?: Record<string, string[]>) => Promise<void>; error?: string; noteError?: string; links: ReactNode;
}) {
  const t = useT()
  const { language } = useLanguage()
  const [rows, dispatch] = useReducer(planReducer, approval.payload.plan, scopeRows)
  const [kind, setKind] = useState<ScopeKind>('entities')
  const [note, setNote] = useState('')
  const [noteTouched, setNoteTouched] = useState(false)
  const [scopeError, setScopeError] = useState(false)
  const [confirmDeny, setConfirmDeny] = useState(false)
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const addRef = useRef<HTMLInputElement>(null)
  const extension = extensionRows(approval.payload)
  const expiry = Date.parse(approval.expires_at)
  const state = approval.state === 'pending' && expiry <= Date.now() ? 'expired' : approval.state
  const pending = state === 'pending'
  const canDecide = pending && !blocked && !checking && (owner || (!approval.requires_owner && editor))
  const editable = canDecide && !extension
  const editedPlan = buildScope(rows)
  const didEdit = JSON.stringify(editedPlan) !== JSON.stringify(buildScope(scopeRows(approval.payload.plan)))
  const summary = typeof approval.payload.summary === 'string' ? approval.payload.summary : undefined
  const phases = Array.isArray(approval.payload.phases) ? approval.payload.phases.filter(phase => typeof phase === 'string') : []
  const original = approval.payload.edited_by || approval.payload.edited_from ? scopeRows(approval.payload.edited_from) : undefined
  const dateFormat = new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' })
  const date = (value?: string | null) => value && Number.isFinite(Date.parse(value)) ? dateFormat.format(new Date(value)) : undefined
  const editedBy = typeof approval.payload.edited_by === 'string' ? approval.payload.edited_by : approval.decided_by
  const noteIssue = noteTouched ? validators.length(guidedLimits.note)(note) : undefined
  const denyError = confirmDeny && !note.trim() ? t('plan.denyReason') : undefined
  const reason = state === 'expired' ? t('plan.expiredReason') : pending && !checking && !(owner || editor) ? t('plan.viewer')
    : pending && approval.requires_owner && !owner && !checking ? t('plan.ownerReason') : undefined

  async function submit(approve: boolean) {
    if (!canDecide || busy) return
    setNoteTouched(true)
    if (validators.length(guidedLimits.note)(note) || (!approve && !note.trim())) {
      noteRef.current?.focus()
      return
    }
    if (approve && editable && didEdit && !Object.keys(editedPlan).length) {
      setScopeError(true)
      addRef.current?.focus()
      return
    }
    await onDecision(approve, note.trim(), approve && editable && didEdit ? editedPlan : undefined)
  }

  function dateFact(key: string, value?: string) {
    return value ? <ListRow title={t(key)} detail={t('common.serverText', { text: value })} /> : null
  }

  return <Card data-testid="plan-card"><Stack gap={4}>
    <h2>{t('common.serverText', { text: approval.subject })}</h2>
    <Row>
      {pending && Number.isFinite(expiry) && <Badge>{t('plan.expires', { date: date(approval.expires_at) ?? '' })}</Badge>}
      {approval.requires_owner && <Badge tone="warning">{t('plan.ownerBadge')}</Badge>}
    </Row>
    {!pending && <div data-testid="plan-state"><Alert tone={state === 'approved' ? 'success' : 'info'}>
      <Stack gap={1}>
        <strong data-testid="plan-done">{knownStates.includes(state) ? t(`plan.states.${state}`) : t('common.serverText', { text: state })}</strong>
        {approval.decision_note && <p>{t('plan.noteValue', { text: approval.decision_note })}</p>}
        {approval.decision_note === 'auto-approved by org policy' && <p>{t('plan.autoPolicy')}</p>}
      </Stack>
    </Alert></div>}
    {summary && <p>{t('common.serverText', { text: summary })}</p>}
    {!!approval.risk_flags.length && <Row data-testid="plan-risks">{approval.risk_flags.map(flag =>
      <Badge tone="warning" key={flag}>{knownRisks.includes(flag) ? t(`plan.risks.${flag}`) : t('common.serverText', { text: flag })}</Badge>)}</Row>}
    {!!phases.length && <Stack data-testid="plan-phases" gap={2}>
      <h3>{t('intake.phases')}</h3><ol className="v2-guided-list">{phases.map((phase, index) => <li key={index}>{t('common.serverText', { text: phase })}</li>)}</ol>
    </Stack>}
    {original && <Card data-testid="plan-edited-from"><Stack gap={2}>
      <h3>{t('plan.editedFrom')}</h3>
      <p>{t('plan.editedFromIntro', { reviewer: reviewer || (editedBy ? t('plan.reviewerId', { id: editedBy.slice(0, 8) }) : t('plan.reviewer')) })}</p>
      <ReviewScope rows={original} />
    </Stack></Card>}
    <Stack data-testid="plan-table" gap={2}>
      {extension && <h3>{t('plan.extension')}</h3>}
      <ReviewScope rows={extension ?? rows} editable={editable} busy={busy}
        onToggle={row => { dispatch({ type: 'toggle', row }); setScopeError(false) }} />
    </Stack>
    <Stack gap={2}>
      {dateFact('plan.created', date(approval.created_at))}
      {dateFact('plan.decided', date(approval.decided_at))}
      {dateFact('plan.spec', approval.bound_spec_hash)}
      {dateFact('plan.commit', approval.bound_commit ?? undefined)}
    </Stack>
    {editable && <Form submitLabel={t('plan.add')} pending={busy} fields={[
      { name: 'kind', label: t('plan.kindToAdd'),
        control: ({ name, disabled, ...attrs }) => <Select name={name} triggerProps={attrs} value={kind} onValueChange={value => setKind(value as ScopeKind)}
          disabled={disabled} options={(owner ? scopeKinds : ['entities'] as const).map(option => ({ value: option, label: t(`plan.kinds.${option}`) }))} /> },
      { name: 'name', label: t('plan.nameToAdd'), validate: [
        validators.required, validators.length(guidedLimits.scopeName),
        ...planNameChecks(rows.filter(row => row.kind === kind).map(row => row.name), editedPlan[kind]?.length ?? 0),
      ], control: attrs => <Input {...attrs} ref={addRef} maxLength={guidedLimits.scopeName} /> },
    ]} onSubmit={fields => {
      dispatch({ type: 'add', row: { kind, name: String(fields.get('name')).trim() } })
      if (addRef.current) addRef.current.value = ''
      setScopeError(false)
    }} />}
    {reason && <div id="plan-gate-reason" data-testid="plan-gate-reason"><ReadOnlyNote>{reason}</ReadOnlyNote></div>}
    {canDecide && <>
      <Field label={t('plan.note')} error={denyError || (noteError && t('common.serverText', { text: noteError })) || (noteIssue && t(noteIssue.key, { ...noteIssue.values, field: t('plan.note') }))}>
        {attrs => <Textarea {...attrs} ref={noteRef} value={note} maxLength={guidedLimits.note} disabled={busy}
          onBlur={() => setNoteTouched(true)} onChange={event => { setNote(event.target.value); setConfirmDeny(false) }} />}
      </Field>
      {didEdit && editable && <p data-testid="plan-edited">{t('plan.editedHint')}</p>}
      {scopeError && <Alert tone="danger">{t('plan.errors.plan_empty')}</Alert>}
      <Row>
        <Button variant="primary" disabled={busy} data-testid="plan-approve" onClick={() => void submit(true).catch(() => undefined)}>
          {t(didEdit && editable ? 'plan.approveEdited' : 'plan.approve')}
        </Button>
        {note.trim() ? <ConfirmDestructive trigger={<Button variant="danger" data-testid="plan-deny" disabled={busy}>{t('plan.deny')}</Button>}
          title={t('plan.denyTitle')} description={t('plan.denyDescription')} action={t('plan.deny')}
          pending={busy} error={error} onConfirm={() => submit(false)} />
          : <Button variant="danger" disabled={busy} data-testid="plan-deny" onClick={() => { setConfirmDeny(true); noteRef.current?.focus() }}>{t('plan.deny')}</Button>}
      </Row>
    </>}
    {links}
  </Stack></Card>
}
