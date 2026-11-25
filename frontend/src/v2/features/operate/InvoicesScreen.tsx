import { useState } from 'react'
import { defaultExponent, formatMinor, invoiceTotals, newIdempotencyKey, parseMajor, toBig } from '../../../shell/money/moneyLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Button, Field, Input, Row, Stack } from '../../ui'
import { amountIssue, currencyIssue, wholeIssue } from '../../validators/operateRuntime'
import { segment, useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import type { Aging, Invoice, InvoiceInput } from './api/money'
import { canWrite } from './api/operate'
import { useOperateDate, useOperateSearch } from './components/Common'
import { LedgerLink, useMoney } from './components/Money'
import { choices, Columns, data, Details, Empty, enumLabel, field, Filter, key, optional, Pager, Panel, Pick, Refresh,
  RuntimeScreen, RuntimeState, selectField, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'

const kinds = ['receivable', 'payable'] as const
const states = ['draft', 'issued', 'partially_paid', 'paid', 'void']
const size = 100
const invoicePath = (id: string) => `/invoices/${segment(id)}` as const

export default function InvoicesScreen(props: LiveProps) {
  return <RuntimeScreen id={props} title={'invoices'}>{session => <Invoices session={session} writable={canWrite(props)} />}</RuntimeScreen>
}
function Invoices({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const money = useMoney()
  const { search, change } = useOperateSearch()
  const [create, setCreate] = useState(false)
  const page = search.page ?? 1
  const kind = kinds.find(kind => kind === search.kind)
  const status = states.find(status => status === search.status)
  const agingKind = search.aging === 'payable' ? 'payable' : 'receivable'
  const invoices = useRuntimeQuery<Page<Invoice>>(session, '/invoices', { kind, status, counterparty: search.q, limit: size, offset: (page - 1) * size })
  const aging = useRuntimeQuery<Aging>(session, '/invoices/aging', { kind: agingKind, as_of: search.asOf })
  const detail = useRuntimeQuery<Invoice>(session, invoicePath(search.view ?? ''), {}, !!search.view)
  const rows = invoices.data?.items ?? []
  const refresh = () => Promise.all([invoices.refetch(), aging.refetch(), ...(search.view ? [detail.refetch()] : [])])
  return <Stack gap={4}>
    <Row><Refresh run={refresh} />{writable && <Button onClick={() => setCreate(!create)}>{t(key(create ? 'close' : 'createInvoice'))}</Button>}</Row>
    <Panel title={'invoices'}>
      <Row>
        <Pick label={t(key('kind'))} value={kind ?? ''} options={choices(t, kinds)} onChange={kind => change({ kind: kind || undefined, page: undefined })} />
        <Pick label={t(key('status'))} value={status ?? ''} options={choices(t, states)} onChange={status => change({ status: status || undefined, page: undefined })} />
        <Filter name="counterparty" max={200} value={search.q} onChange={q => change({ q, page: undefined })} />
      </Row>
      {invoices.isPending || invoices.isError ? <RuntimeState error={invoices.error} retry={invoices.refetch} /> : rows.length ?
        <Stack>
          <Columns label={'invoices'} names={['number', 'kind', 'counterparty', 'dueDate', 'status', 'total', 'paid', 'outstanding', 'actions']} rows={rows.map(i => ({
            id: i.id, cells: [data(t, i.number), enumLabel(t, i.kind), data(t, i.counterparty), data(t, i.due_date), enumLabel(t, i.status),
              money(i.total_minor, i.currency, i.exponent), money(i.paid_minor, i.currency, i.exponent), money(i.outstanding_minor, i.currency, i.exponent),
              <Button onClick={() => change({ view: i.id, edit: undefined })}>{t(key('open'))}</Button>],
          }))} />
          <Columns label={'invoiceTotals'} names={['currency', 'total', 'paid', 'outstanding']} rows={invoiceTotals(rows).map(v => ({ id: v.currency,
            cells: [data(t, v.currency), money(v.total, v.currency, v.exponent), money(v.paid, v.currency, v.exponent), money(v.outstanding, v.currency, v.exponent)],
          }))} />
        </Stack> : <Empty message="noInvoices" action={writable ? 'createInvoice' : undefined} onAction={writable ? () => setCreate(true) : invoices.refetch} />}
      <Pager label={'invoices'} page={page} size={size} total={invoices.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.view && <Panel title={'invoice'}>
      <Row><Button onClick={() => change({ view: undefined, edit: undefined })}>{t(key('close'))}</Button></Row>
      {detail.isPending || detail.isError ? <RuntimeState error={detail.error} retry={detail.refetch} /> :
        <InvoiceDetails key={detail.data.id} session={session} value={detail.data} writable={writable} reload={detail.refetch} />}
    </Panel>}
    <Panel title={'agingReport'}>
      <Row><Pick label={t(key('agingFor'))} value={agingKind} options={choices(t, kinds).slice(1)} onChange={aging => change({ aging })} />
        <Filter name="asOf" type="date" value={search.asOf} onChange={asOf => change({ asOf })} /></Row>
      {aging.isPending || aging.isError ? <RuntimeState error={aging.error} retry={aging.refetch} /> : aging.data.currencies.length ?
        <Columns label={'agingReport'} names={['currency', 'bucket', 'count', 'amount']} rows={aging.data.currencies.flatMap(c => [
          { id: c.currency + ':current', cells: [data(t, c.currency), t(key('current')), data(t, c.current_count), money(c.current_minor, c.currency)] },
          ...c.buckets.map((b, i) => ({ id: c.currency + ':' + i, cells: [data(t, c.currency), data(t, b.label), data(t, b.count), money(b.amount_minor, c.currency)] })),
          { id: c.currency + ':total', cells: [data(t, c.currency), t(key('total')), data(t, c.count), money(c.total_minor, c.currency)] },
        ])} /> : <Empty message="noAging" onAction={aging.refetch} />}
    </Panel>
    {writable && create && <InvoiceForm session={session} onSaved={i => { setCreate(false); change({ view: i.id }) }} />}
  </Stack>
}

function InvoiceDetails({ session, value, writable, reload }: { session: Session; value: Invoice; writable: boolean; reload: () => unknown }) {
  const t = useT()
  const money = useMoney()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const [reason, setReason] = useState('')
  const [paymentKey, setPaymentKey] = useState(newIdempotencyKey)
  const path = invoicePath(value.id)
  const issue = useRuntimeWrite<undefined, Invoice>(session, path + '/issue' as `/invoices/${string}`)
  const payment = useRuntimeWrite<{ idempotency_key: string; amount_minor: number; paid_on?: string; reference?: string }, Invoice>(session, `${path}/payments`)
  const voidInvoice = useRuntimeWrite<{ reason?: string }, Invoice>(session, `${path}/void`)
  const canPay = ['issued', 'partially_paid'].includes(value.status)
  const amount = (v: Invoice['total_minor']) => money(v, value.currency, value.exponent)
  return <Stack>
    <Details values={[[ 'number', data(t, value.number)], ['counterparty', data(t, value.counterparty)], ['counterpartyRef', data(t, value.counterparty_ref)],
      ['status', enumLabel(t, value.status)], ['subtotal', amount(value.subtotal_minor)], ['tax', amount(value.tax_minor)],
      ['total', amount(value.total_minor)], ['paid', amount(value.paid_minor)], ['outstanding', amount(value.outstanding_minor)],
      ['created', date(value.created_at)], ['issuedAt', date(value.issued_at)], ['voidedAt', date(value.voided_at)],
      ['issueDate', data(t, value.issue_date)], ['dueDate', data(t, value.due_date)], ['notes', data(t, value.notes)]]} />
    <Row>{value.issue_transaction_id && <LedgerLink projectId={session.projectId} id={value.issue_transaction_id} label={'issueTransaction'} />}
      {value.void_transaction_id && <LedgerLink projectId={session.projectId} id={value.void_transaction_id} label={'voidTransaction'} />}</Row>
    <Columns label={'lines'} names={['description', 'quantity', 'unitPrice', 'taxRate', 'subtotal', 'tax', 'total']} rows={value.lines.map(l => ({ id: l.id,
      cells: [data(t, l.description), data(t, l.quantity), amount(l.unit_price_minor), data(t, l.tax_rate), amount(l.net_minor), amount(l.tax_minor), amount(l.gross_minor)],
    }))} />
    {!!value.payments.length && <Columns label={'payments'} names={['paidOn', 'amount', 'reference', 'transaction']} rows={value.payments.map(p => ({
      id: p.id, cells: [data(t, p.paid_on), amount(p.amount_minor), data(t, p.reference), <LedgerLink projectId={session.projectId} id={p.ledger_transaction_id} />],
    }))} />}
    {writable && <Row>
      {value.status === 'draft' && <>
        <Button onClick={() => change({ edit: search.edit === 'draft' ? undefined : 'draft' })}>{t(key('editDraft'))}</Button>
        <Button disabled={issue.isPending} onClick={() => issue.mutate(undefined)}>{t(key('issueInvoice'))}</Button>
      </>}
      {canPay && <Button onClick={() => change({ edit: search.edit === 'payment' ? undefined : 'payment' })}>{t(key('recordPayment'))}</Button>}
      {['draft', 'issued'].includes(value.status) && !value.payments.length && <ConfirmDestructive trigger={<Button variant="danger">{t(key('voidInvoice'))}</Button>}
        title={t(key('voidInvoice'))} description={t(key('voidHelp'))} action={t(key('voidYes'))} pending={voidInvoice.isPending}
        onConfirm={async () => { await voidInvoice.mutateAsync({ reason: reason.trim() || undefined }) }}>
        <Field label={t(key('reason'))}>{attrs => <Input {...attrs} maxLength={500} value={reason} onChange={e => setReason(e.target.value)} />}</Field>
      </ConfirmDestructive>}
    </Row>}
    {writable && search.edit === 'draft' && value.status === 'draft' &&
      <InvoiceForm session={session} value={value} onSaved={() => change({ edit: undefined })} />}
    {writable && search.edit === 'payment' && canPay && <Form key={paymentKey} fields={[
      field(t, 'amount', { required: true, max: 24, validate: v => amountIssue(v, value.exponent, true, toBig(value.outstanding_minor)) }),
      field(t, 'paidOn', { type: 'date' }), field(t, 'reference', { max: 128 }), field(t, 'idempotency', { value: paymentKey, max: 128, required: true }),
    ]} serverErrors={serverFields(payment.error, { amount_minor: 'amount', idempotency_key: 'idempotency', paid_on: 'paidOn' })} pending={payment.isPending} submitLabel={t(key('recordPayment'))} onSubmit={form => payment.mutate({
      amount_minor: Number(parseMajor(text(form, 'amount'), value.exponent)), paid_on: optional(form, 'paidOn'), reference: optional(form, 'reference'),
      idempotency_key: text(form, 'idempotency'),
    }, { onSuccess: () => { setPaymentKey(newIdempotencyKey()); change({ edit: undefined }) } })} />}
    <WriteStatus error={issue.error} reload={reload} success={issue.isSuccess ? t(key('invoiceIssued')) : undefined} />
    <WriteStatus error={payment.error} reload={reload} replayed={payment.data?.replayed} success={payment.isSuccess ? t(key('paymentRecorded')) : undefined} />
    <WriteStatus error={voidInvoice.error} reload={reload} success={voidInvoice.isSuccess ? t(key('invoiceVoided')) : undefined} />
  </Stack>
}

function InvoiceForm({ session, value, onSaved }: { session: Session; value?: Invoice; onSaved: (value: Invoice) => void }) {
  const t = useT()
  const [count, setCount] = useState(value?.lines.length || 1)
  const mutation = useRuntimeWrite<InvoiceInput, Invoice>(session, value ? invoicePath(value.id) : '/invoices', value ? 'PATCH' : 'POST')
  const lines = Array.from({ length: count }, (_, i) => i)
  const exponent = (currency: string) => currency === value?.currency ? value.exponent : defaultExponent(currency)
  return <Panel title={value ? 'editDraft' : 'createInvoice'}>
    <Form fields={[
      ...(!value ? [selectField(t, 'kind', choices(t, kinds, 'choose'), 'receivable')] : []),
      field(t, 'counterparty', { value: value?.counterparty, required: true, max: 200 }),
      field(t, 'counterpartyRef', { value: value?.counterparty_ref ?? undefined, max: 64 }),
      field(t, 'currency', { value: value?.currency, required: true, max: 3, validate: currencyIssue }),
      field(t, 'issueDate', { value: value?.issue_date ?? undefined, type: 'date' }),
      field(t, 'dueDate', { value: value?.due_date ?? undefined, type: 'date' }),
      field(t, 'notes', { value: value?.notes ?? undefined, max: 500, area: true }),
      ...lines.flatMap(i => {
        const line = value?.lines[i]
        return [
          field(t, 'description', { required: true, value: line?.description, max: 500 }),
          field(t, 'quantity', { required: true, value: String(line?.quantity ?? 1), validate: v => wholeIssue(v, 1, 1_000_000_000) }),
          field(t, 'unitPrice', { required: true, value: line && formatMinor(line.unit_price_minor, value.exponent).replaceAll(',', ''), max: 24,
            validate: (v, form) => amountIssue(v, exponent(text(form, 'currency').toUpperCase())) }),
          field(t, 'taxRate', { value: line?.tax_rate ?? undefined, max: 32 }),
        ].map(f => ({ ...f, name: f.name + i, label: t(key('invoiceLineField'), { line: i + 1, field: f.label }) }))
      }),
    ]} serverErrors={serverFields(mutation.error, { counterparty_ref: 'counterpartyRef', issue_date: 'issueDate', due_date: 'dueDate' }, path => {
      const line = /^lines\.(\d+)\.(description|quantity|unit_price_minor|tax_rate)$/.exec(path)
      if (!line) return undefined
      const name = line[2] === 'unit_price_minor' ? 'unitPrice' : line[2] === 'tax_rate' ? 'taxRate' : line[2]
      return name + line[1]
    })} pending={mutation.isPending} submitLabel={t(key(value ? 'save' : 'createDraft'))} actions={<>
      <Button disabled={count >= 200 || mutation.isPending} onClick={() => setCount(count + 1)}>{t(key('addLine'))}</Button>
      <Button disabled={count < 2 || mutation.isPending} onClick={() => setCount(count - 1)}>{t(key('removeLine'))}</Button>
    </>} onSubmit={form => {
      const currency = text(form, 'currency').toUpperCase()
      mutation.mutate({
        ...(!value ? { kind: text(form, 'kind') as Invoice['kind'] } : {}),
        currency, counterparty: text(form, 'counterparty'), counterparty_ref: optional(form, 'counterpartyRef') ?? null,
        issue_date: optional(form, 'issueDate') ?? null, due_date: optional(form, 'dueDate') ?? null, notes: optional(form, 'notes') ?? null,
        lines: lines.map(i => ({ description: text(form, 'description' + i), quantity: Number(text(form, 'quantity' + i)),
          unit_price_minor: Number(parseMajor(text(form, 'unitPrice' + i), exponent(currency))), tax_rate: optional(form, 'taxRate' + i) })),
      }, { onSuccess: result => onSaved(result.data) })
    }} />
    <WriteStatus error={mutation.error} reload={mutation.reset} />
  </Panel>
}
