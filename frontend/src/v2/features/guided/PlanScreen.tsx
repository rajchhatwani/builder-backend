import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useRouter, useSearch } from '@tanstack/react-router'
import { useState } from 'react'
import { useT } from '../../i18n'
import { ConflictBanner, PageHeader, ReadOnlyNote, SettingsSection } from '../../patterns'
import { Alert, Button, Card, EmptyState, Field, Row, Select, Skeleton, Stack, useToast } from '../../ui'
import { approvalOptions, errorCode, errorStatus, fieldMessage, useGuidedAccess, usePlanDecision } from './api/guided'
import type { Approval } from './api/guided'
import { GuidedLoadError, useGuidedError } from './components/GuidedFeedback'
import { PlanReview } from './components/PlanReview'
import { activePlan, approvalBinding } from './state/plan'

export default function PlanScreen() {
  const { run, approval } = useSearch({ from: '/projects/$projectId/$section' })
  return <PlanScreenForRun key={`${run}:${approval}`} run={run} selected={approval} />
}

function PlanScreenForRun({ run, selected }: { run?: string; selected?: string }) {
  const t = useT()
  const toast = useToast()
  const router = useRouter()
  const { projectId } = useParams({ from: '/projects/$projectId/$section' })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const approvals = useQuery(approvalOptions(projectId, run))
  const access = useGuidedAccess(projectId)
  const decision = usePlanDecision(projectId, run, approvalBinding)
  const describeError = useGuidedError()
  const [changedId, setChangedId] = useState<string>()
  const staleReview = decision.data?.changed || errorStatus(decision.error) === 409
  const latest = changedId && approvals.data?.find(item => item.id === changedId)
  const approval = latest || approvals.data?.find(item => item.id === selected && item.kind === 'A') || activePlan(approvals.data ?? [])
  const selectable = approvals.data?.filter(item => item.kind === 'A' && item.state === 'pending') ?? []
  const noteError = fieldMessage(decision.error, 'note')
  const deniedByServer = errorCode(decision.error) === 'approval_forbidden' || errorCode(decision.error) === 'separation_of_duties'

  function reload() {
    setChangedId(undefined)
    decision.reset()
    void approvals.refetch()
  }

  async function decide(seen: Approval, approve: boolean, note: string, plan?: Record<string, string[]>) {
    const opening = router.state.location.href
    const result = await decision.mutateAsync({ seen, approve, note, plan })
    if (result.changed) {
      setChangedId(result.approval.id)
      throw new Error('approval_changed')
    }
    toast({ title: t(approve ? plan ? 'plan.editedApproved' : 'plan.approved' : 'plan.denied'), tone: 'success' })
    if (!run && router.state.location.href === opening) {
      await navigate({ search: { run: seen.run_id, approval: seen.id }, replace: true })
    }
  }

  const failureCode = errorCode(decision.error)
  const error = decision.error == null ? undefined : (
    failureCode && ['plan_empty', 'payload_hash_required', 'plan_edit_not_allowed', 'approval_forbidden', 'separation_of_duties'].includes(failureCode)
      ? t(`plan.errors.${failureCode}`) : describeError(decision.error)
  )

  return <Stack gap={5} data-testid="plan-page">
    <PageHeader title={t('plan.title')} description={t('plan.intro')} />
    {approvals.isPending ? <Card><Skeleton lines={8} label={t('plan.loading')} /></Card>
      : approvals.isError && !approvals.data ? <GuidedLoadError error={approvals.error} retry={reload} label={t('plan.loadError')} /> : <>
        {access.failed && <GuidedLoadError error={access.account.error ?? access.members.error} retry={access.retry} label={t('guided.accessError')} />}
        {approvals.isError && <GuidedLoadError error={approvals.error} retry={reload} label={t('plan.loadError')} />}
        {staleReview && <Stack gap={2} data-testid="plan-changed">
          <ConflictBanner onReload={reload}>{error ?? t('plan.changed')}</ConflictBanner>
        </Stack>}
        {error && !staleReview && !noteError && <Alert tone="danger">{error}</Alert>}
        {selectable.length > 1 && <SettingsSection title={t('plan.waiting')}>
          <Field label={t('plan.choose')}>{attrs => <Select triggerProps={attrs} value={selectable.some(item => item.id === approval?.id) ? approval?.id : undefined}
            options={selectable.map(item => ({ value: item.id, label: t('plan.requestOption', { subject: item.subject, run: item.run_id.slice(0, 8) }) }))}
            disabled={decision.isPending}
            onValueChange={id => {
              const chosen = selectable.find(item => item.id === id)
              if (chosen) void navigate({ search: { run: chosen.run_id, approval: chosen.id } })
            }} />}</Field>
        </SettingsSection>}
        {approval ? <PlanReview key={approvalBinding(approval)} approval={approval}
          owner={access.role === 'owner'} editor={access.role === 'editor'} checking={access.pending}
          blocked={Boolean(staleReview || deniedByServer)} busy={decision.isPending}
          reviewer={access.members.data?.find(member => member.user_id === (approval.payload.edited_by || approval.decided_by))?.name}
          onDecision={(approve, note, plan) => decide(approval, approve, note, plan)} error={error} noteError={noteError}
          links={<Row>
            <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'build' }} search={{ run: approval.run_id }}>{t('plan.back')}</Link></Button>
            <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId, section: 'approvals' }}>{t('nav.approvals')}</Link></Button>
          </Row>} />
          : <div data-testid="plan-empty">
            {!access.pending && !access.failed && access.role !== 'owner' && access.role !== 'editor' && <ReadOnlyNote />}
            <EmptyState title={t('plan.empty')} description={t('plan.emptyIntro')} action={<Button asChild variant="primary">
              <Link to="/projects/$projectId/$section" params={{ projectId, section: 'intake' }}>{t('plan.describe')}</Link>
            </Button>} />
          </div>}
      </>}
  </Stack>
}
