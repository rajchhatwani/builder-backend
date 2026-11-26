import { useT } from '../../../i18n'
import { Badge, CodeBlock, Disclosure, Stack, Table } from '../../../ui'
import type { MigrationPlanResponse } from '../api/ship'
import { useShipFormat } from './Common'

export function MigrationReview({ migration }: { migration?: MigrationPlanResponse }) {
  const t = useT()
  const { columns } = useShipFormat()
  if (!migration?.plan) return <p>{t('ship.noPlanReturned')}</p>
  const { plan } = migration
  return <Stack>
    {migration.old_snapshot_unusable ? <p>{t('ship.unreadablePreview')}</p> :
      migration.first_generation ? <p>{t('ship.firstGeneration')}</p> :
        migration.against_generation_id && <p>{t('ship.baselineId', { id: migration.against_generation_id })}</p>}
    {plan.requires_backfill && <p>{t('ship.backfill')}</p>}
    {plan.ignored_sections.length > 0 && <p>{t('ship.ignoredSections', { value: plan.ignored_sections.join(', ') })}</p>}
    {plan.steps.length === 0 ? <p>{t('ship.noMigration')}</p> : <>
      <ol className="v2-ship-flow" aria-label={t('ship.migrationOrder')}>
        {plan.steps.map(step => <li key={step.seq}>{t('ship.stepOrder', { seq: step.seq, kind: step.kind.replaceAll('_', ' '), safety: step.safety })}</li>)}
      </ol>
      <Table label={t('ship.migrationPlan')} columns={columns('phase', 'step', 'where', 'safety', 'why')}
        rows={plan.steps.map(step => ({ id: String(step.seq), cells: [
          t('ship.value', { value: step.phase }),
          t('ship.value', { value: step.kind.replaceAll('_', ' ') }),
          <code>{t('ship.value', { value: step.field ? step.table + '.' + step.field : step.table })}</code>,
          <Badge tone={step.safety === 'destructive' ? 'danger' : 'neutral'}>{t('ship.value', { value: step.safety })}</Badge>,
          <Stack gap={1}>{[step.reason, step.suggested_action, step.backfill_strategy, step.note].filter(Boolean)
            .map((value, index) => <p key={index}>{t('ship.value', { value: value ?? '' })}</p>)}</Stack>,
        ] }))} />
    </>}
    {migration.text && <Disclosure label={t('ship.plainText')}><CodeBlock code={migration.text} /></Disclosure>}
  </Stack>
}
