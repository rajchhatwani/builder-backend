import { useState } from 'react'
import { newIdempotencyKey } from '../../../shell/money/moneyLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Alert, Button, Row, Stack } from '../../ui'
import { sellerIssue } from '../../validators/operateRuntime'
import { segment, useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import type { Invoice, Payout, PayoutTotal } from './api/money'
import { canWrite } from './api/operate'
import { SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { LedgerLink, useMoney } from './components/Money'
import { Columns, data, Details, Empty, field, Filter, key, Pager, Panel, Refresh, RuntimeScreen, RuntimeState,
  selectField, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'

const path = '/payouts'
const size = 100
type Input = { invoice_id: string; seller: string; idempotency_key: string }

export default function PayoutsScreen(props: LiveProps) {
  return <RuntimeScreen id={props} title={'payouts'}>{session => <Payouts session={session} writable={canWrite(props)} />}</RuntimeScreen>
}
function Payouts({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const money = useMoney()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const page = search.page ?? 1
  const list = useRuntimeQuery<Page<Payout>>(session, path, { limit: size, offset: (page - 1) * size, seller: search.seller, invoice_id: search.invoice })
  const totals = useRuntimeQuery<PayoutTotal[]>(session, '/payouts/totals', { seller: search.seller })
  const invoices = useRuntimeQuery<Page<Invoice>>(session, '/invoices', { kind: 'receivable', status: 'paid', limit: 200 }, writable)
  const paid = useRuntimeQuery<Page<Payout>>(session, path, { limit: 200 }, writable)
  const detail = useRuntimeQuery<Payout>(session, `/payouts/${segment(search.view ?? '')}`, {}, !!search.view)
  const eligible = (invoices.data?.items ?? []).filter(i => !paid.data?.items.some(p => p.invoice_id === i.id))
  const rows = list.data?.items ?? []
  const payout = detail.data
  const amounts = (p: Payout | PayoutTotal) => [money(p.gross_minor, p.currency), money(p.commission_minor, p.currency), money(p.seller_minor, p.currency)]
  const refresh = () => Promise.all([list.refetch(), totals.refetch(), ...(writable ? [invoices.refetch(), paid.refetch()] : []), ...(search.view ? [detail.refetch()] : [])])
  return <Stack gap={4}>
    <Row><Refresh run={refresh} /><SectionLink id={session.projectId} section="invoicingsettings" label={t(key('invoicingSettings'))} /></Row>
    <Panel title={'payouts'}>
      <Row><Filter name="seller" max={64} value={search.seller} onChange={seller => change({ seller, page: undefined })} />
        <Filter name="invoiceId" max={36} value={search.invoice} onChange={invoice => change({ invoice, page: undefined })} /></Row>
      {list.isPending || list.isError ? <RuntimeState error={list.error} retry={list.refetch} /> : rows.length ?
        <Columns label={'payouts'} names={['seller', 'invoice', 'gross', 'commission', 'sellerAmount', 'created', 'actions']} rows={rows.map(p => ({
          id: p.id, cells: [data(t, p.seller), <SectionLink id={session.projectId} section="invoices" search={{ view: p.invoice_id }}
            label={data(t, invoices.data?.items.find(i => i.id === p.invoice_id)?.number ?? p.invoice_id)} />,
            ...amounts(p), date(p.created_at), <Button onClick={() => change({ view: p.id })}>{t(key('open'))}</Button>],
        }))} /> : <Empty message="noPayouts" onAction={list.refetch} />}
      <Pager label={'payouts'} size={size} page={page} total={list.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    <Panel title={'sellerTotals'}>
      {totals.isPending || totals.isError ? <RuntimeState error={totals.error} retry={totals.refetch} /> : totals.data.length ?
        <Columns label={'sellerTotals'} names={['seller', 'currency', 'count', 'gross', 'commission', 'sellerAmount']} rows={totals.data.map(p => ({
          id: p.seller + ':' + p.currency, cells: [data(t, p.seller), data(t, p.currency), data(t, p.count), ...amounts(p)],
        }))} /> : <Empty message="noPayoutTotals" onAction={totals.refetch} />}
    </Panel>
    {search.view && <Panel title={'payout'}>
      <Row><Button onClick={() => change({ view: undefined })}>{t(key('close'))}</Button></Row>
      {detail.isPending || detail.isError || !payout ? <RuntimeState error={detail.error} retry={detail.refetch} /> :
        <Stack><Details values={[['seller', data(t, payout.seller)], ['commissionBp', data(t, payout.commission_bp)],
          ...amounts(payout).map((amount, i): [string, string] => [['gross', 'commission', 'sellerAmount'][i], amount]),
          ['created', date(payout.created_at)]]} />
          <Row><LedgerLink projectId={session.projectId} id={payout.split_transaction_id} label={'splitTransaction'} />
            {payout.payout_transaction_id && <LedgerLink projectId={session.projectId} id={payout.payout_transaction_id} label={'payoutTransaction'} />}</Row>
        </Stack>}
    </Panel>}
    {writable && <Panel title={'runPayout'}>
      {invoices.isPending || paid.isPending || invoices.isError || paid.isError ? <RuntimeState error={invoices.error ?? paid.error} retry={refresh} /> :
        <RunPayout session={session} eligible={eligible} refresh={refresh} />}
    </Panel>}
  </Stack>
}

function RunPayout({ session, eligible, refresh }: { session: Session; eligible: Invoice[]; refresh: () => unknown }) {
  const t = useT()
  const money = useMoney()
  const [idempotency, setIdempotency] = useState(newIdempotencyKey)
  const [draft, setDraft] = useState<Input>()
  const [open, setOpen] = useState(false)
  const mutation = useRuntimeWrite<Input, Payout>(session, '/payouts/run')
  const selected = eligible.find(i => i.id === draft?.invoice_id)
  const existingPayout = useRuntimeQuery<Page<Payout>>(session, path, { invoice_id: draft?.invoice_id, limit: 1 }, open && !!draft)
  const alreadyPaid = !!existingPayout.data?.items.length
  return <Stack>
    {eligible.length ? <Form key={idempotency} fields={[
      selectField(t, 'paidInvoice', eligible.map(i => ({ value: i.id, label: t(key('paidInvoiceItem'), {
        number: i.number ?? i.id, name: i.counterparty, amount: money(i.subtotal_minor, i.currency, i.exponent),
      }) }))),
      field(t, 'seller', { required: true, max: 64, validate: sellerIssue }),
      field(t, 'idempotency', { value: idempotency, required: true, max: 128 }),
    ]} serverErrors={serverFields(mutation.error, { invoice_id: 'paidInvoice', idempotency_key: 'idempotency' })} submitLabel={t(key('runPayout'))} pending={mutation.isPending} onSubmit={form => {
      setDraft({ invoice_id: text(form, 'paidInvoice'), seller: text(form, 'seller'), idempotency_key: text(form, 'idempotency') })
      setOpen(true)
    }} /> : <Empty message="noEligibleInvoices" onAction={refresh} />}
    <ConfirmDestructive open={open} onOpenChange={setOpen} title={t(key('runPayout'))}
      description={t(key('payoutHelp'), { amount: selected ? money(selected.subtotal_minor, selected.currency, selected.exponent) : '', seller: draft?.seller ?? '' })}
      action={t(key('payoutYes'))} disabled={!draft || alreadyPaid || !existingPayout.data || existingPayout.isError} pending={mutation.isPending} onConfirm={async () => {
        if (draft) await mutation.mutateAsync(draft)
        setIdempotency(newIdempotencyKey())
      }}>
      {(existingPayout.isPending || existingPayout.isError) && <RuntimeState error={existingPayout.error} retry={existingPayout.refetch} lines={2} />}
      {alreadyPaid && <Alert tone="warning">{t(key('alreadyPaidOut'))}</Alert>}
    </ConfirmDestructive>
    <WriteStatus error={mutation.error} reload={refresh} replayed={mutation.data?.replayed} success={mutation.isSuccess ? t(key('payoutRan')) : undefined} />
  </Stack>
}
