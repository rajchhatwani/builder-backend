import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { Button, Card, Dialog, EmptyState, Field, Row, Select, Stack, Table } from '../../../ui'
import { webhookAttemptsOptions, webhookDeliveriesOptions } from '../api/liveWebhooks'
import type { LiveSession } from '../api/liveWebhooks'
import { BlockLoad } from './BlockStatus'

const limits = ['25', '50', '100', '200']
export const deliveryLimit = (limit?: string) => limits.includes(limit ?? '') ? Number(limit) : 50

export function WebhookDeliveries({ id, session, sub, attempt, limit, onLimit, onAttempt }: {
  id: string; session: LiveSession; sub: string; attempt?: string; limit: number;
  onLimit: (limit: string) => void; onAttempt: (attempt?: string) => void;
}) {
  const t = useT()
  const query = useQuery(webhookDeliveriesOptions(id, session, sub, limit))
  const label = t('connectA2.live.deliveries')
  const columns = ['event', 'eventId', 'status', 'attempts', 'httpCode', 'lastError', 'created', 'finished', 'actions']
  return <Card><Stack>
    <h2>{label}</h2>
    <Row>
      <Field label={t('connectA2.live.limit')}>{attrs => <Select value={String(limit)} onValueChange={onLimit} triggerProps={attrs}
        options={limits.map(value => ({ value, label: t('schema.option', { value }) }))} />}</Field>
      <Button onClick={() => void query.refetch()}>{t('common.reload')}</Button>
    </Row>
    {!query.data ? <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectA2.live.loadDeliveries" />
      : query.data.length === 0 ? <EmptyState title={t('connectA2.live.noDeliveries')} /> : <Table label={label}
        columns={columns.map(id => ({ id, label: t('connectA2.live.' + id) }))} rows={query.data.map(item => ({
          id: item.id, cells: [item.event_type, item.event_id, item.status, item.attempts, item.last_status_code, item.last_error,
            formatWebhookDate(item.created_at), item.finished_at && formatWebhookDate(item.finished_at),
            <Button onClick={() => onAttempt(item.id)}>{t('connectA2.live.attempts')}</Button>],
        }))} />}
    {attempt && <Dialog title={t('connectA2.live.attemptTitle')} open onOpenChange={open => { if (!open) onAttempt() }}>
      <Attempts id={id} session={session} attempt={attempt} />
    </Dialog>}
  </Stack></Card>
}

function Attempts({ id, session, attempt }: { id: string; session: LiveSession; attempt: string }) {
  const t = useT()
  const query = useQuery(webhookAttemptsOptions(id, session, attempt))
  if (!query.data) return <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey="connectA2.live.loadAttempts" />
  if (!query.data.length) return <EmptyState title={t('connectA2.live.noAttempts')} />
  return <Table label={t('connectA2.live.attemptTitle')}
    columns={['attempt', 'outcome', 'httpCode', 'duration', 'created'].map(id => ({ id, label: t('connectA2.live.' + id) }))}
    rows={query.data.map((item, index) => ({ id: String(index), cells: [
      item.attempt, item.outcome, item.status_code, t('connectA2.live.milliseconds', { value: item.duration_ms }), formatWebhookDate(item.created_at),
    ] }))} />
}

export function formatWebhookDate(value: string) {
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
