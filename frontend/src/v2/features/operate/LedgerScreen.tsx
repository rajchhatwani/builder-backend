import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { formatMinor, parseMajor, newIdempotencyKey, toBig } from '../../../shell/ledger/ledgerLogic'
import { defaultExponent } from '../../../shell/money/moneyLogic'
import type { Account, AccountEntry, Balances, Entry, Transaction } from '../../../shell/ledger/ledgerLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Alert, Button, Field, Input, Row, Stack } from '../../ui'
import { accountCodeIssue, amountIssue, currencyIssue, idempotencyIssue } from '../../validators/operateRuntime'
import { allLedgerAccounts, segment, useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Details, Empty, enumLabel, field, Filter, key, optional, Pager, Panel, Refresh,
  RuntimeScreen, RuntimeState, selectField, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { canWrite } from './api/operate'

const kinds = ['asset', 'liability', 'equity', 'income', 'expense']
const accountsPath = '/ledger/accounts'
const transactionPath = '/ledger/transactions'
const size = 20
export default function LedgerScreen(props: LiveProps) {
  return <RuntimeScreen id={props} title={'ledger'}>{session => <Ledger session={session} writable={canWrite(props)} />}</RuntimeScreen>
}
function Ledger({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const page = search.page ?? 1
  const historyPage = search.historyPage ?? 1
  const accountPage = search.matchPage ?? 1
  const accounts = useRuntimeQuery<Page<Account>>(session, accountsPath, { limit: 200, offset: (accountPage - 1) * 200, currency: search.currency })
  const balances = useRuntimeQuery<Balances & { truncated: boolean }>(session, '/ledger/balances', { currency: search.currency })
  const transactions = useRuntimeQuery<Page<Transaction>>(session, transactionPath, { limit: size, offset: (page - 1) * size, account_id: search.account })
  const history = useRuntimeQuery<Page<AccountEntry>>(session, `/ledger/accounts/${segment(search.edit ?? '')}/entries`, { limit: 50, offset: (historyPage - 1) * 50 }, !!search.edit)
  const detail = useRuntimeQuery<Transaction>(session, `/ledger/transactions/${segment(search.view ?? '')}`, {}, !!search.view)
  const date = useOperateDate()
  const [create, setCreate] = useState(false)
  const rows = accounts.data?.items ?? []
  const requestsAllAccounts = writable && !!accounts.data && (!!search.currency || accountPage > 1 || accounts.data.total > 200)
  const allAccounts = useQuery(allLedgerAccounts<Account>(session, requestsAllAccounts))
  const postingAccounts = requestsAllAccounts ? allAccounts.data?.items ?? [] : rows
  const money = (amount: Entry['amount_minor'], currency: string, exponent = postingAccounts.find(a => a.currency === currency)?.exponent ?? defaultExponent(currency)) =>
    data(t, currency + ' ' + formatMinor(amount, exponent))
  const refresh = () => Promise.all([accounts.refetch(), balances.refetch(), transactions.refetch(),
    ...(requestsAllAccounts ? [allAccounts.refetch()] : []), ...(search.edit ? [history.refetch()] : []), ...(search.view ? [detail.refetch()] : [])])
  return <Stack gap={4}>
    <Row><Refresh run={refresh} /><Filter name="currency" max={3} value={search.currency} onChange={currency => change({ currency: currency?.toUpperCase(), matchPage: undefined })} /></Row>
    <Panel title={'accounts'}>
      {accounts.isPending || accounts.isError ? <RuntimeState error={accounts.error} retry={accounts.refetch} /> :
        !rows.length ? <Empty message="noAccounts" action={writable ? 'createAccount' : undefined} onAction={writable ? () => setCreate(true) : accounts.refetch} /> :
          <Columns label={'accounts'} names={['code', 'name', 'kind', 'currency', 'created', 'actions']} rows={rows.map(a => ({
            id: a.id, cells: [data(t, a.code), data(t, a.name), enumLabel(t, a.kind), data(t, a.currency), date(a.created_at),
              <Row><Button onClick={() => change({ edit: a.id, historyPage: undefined })}>{t(key('history'))}</Button>
                <Button onClick={() => change({ account: a.id, page: undefined })}>{t(key('transactions'))}</Button></Row>],
          }))} />}
      <Pager label={'accounts'} page={accountPage} size={200} total={accounts.data?.total ?? 0} change={matchPage => change({ matchPage })} />
      {writable && !create && rows.length > 0 && <Row><Button onClick={() => setCreate(true)}>{t(key('createAccount'))}</Button></Row>}
      {writable && create && <CreateAccount session={session} />}
    </Panel>
    {search.edit && <Panel title={'history'}>
      <Row><Button onClick={() => change({ edit: undefined, historyPage: undefined })}>{t(key('close'))}</Button></Row>
      {history.isPending || history.isError ? <RuntimeState error={history.error} retry={history.refetch} /> : history.data.items.length ?
        <Columns label={'history'} names={['posted', 'description', 'debit', 'credit', 'transaction']} rows={history.data.items.map(e => ({
          id: e.id, cells: [date(e.posted_at), data(t, e.description), e.direction === 'debit' ? money(e.amount_minor, e.currency) : data(t, null),
            e.direction === 'credit' ? money(e.amount_minor, e.currency) : data(t, null), <Button onClick={() => change({ view: e.transaction_id })}>{t(key('open'))}</Button>],
        }))} /> : <Empty message="noEntries" onAction={history.refetch} />}
      <Pager label={'history'} page={historyPage} size={50} total={history.data?.total ?? 0} change={historyPage => change({ historyPage })} />
    </Panel>}
    <Panel title={'balances'}>
      {balances.isPending || balances.isError ? <RuntimeState error={balances.error} retry={balances.refetch} /> : balances.data.items.length ?
        <Stack>
          <Columns label={'balances'} names={['code', 'name', 'debit', 'credit', 'balance']} rows={balances.data.items.map(a => ({
            id: a.account_id, cells: [data(t, a.code), data(t, a.name), money(a.debit_total_minor, a.currency, a.exponent),
              money(a.credit_total_minor, a.currency, a.exponent), money(a.balance_minor, a.currency, a.exponent)],
          }))} />
          {balances.data.truncated && <Alert tone="warning">{t(key('balancesTruncated'))}</Alert>}
          <Details values={balances.data.totals.map(total => ['total', money(total.sum_minor, total.currency)])} />
          <Alert tone={balances.data.totals.every(total => toBig(total.sum_minor) === 0n) ? 'success' : 'danger'}>
            {t(key(balances.data.totals.every(total => toBig(total.sum_minor) === 0n) ? 'balanced' : 'unbalanced'))}
          </Alert>
        </Stack> : <Empty message="noBalances" onAction={balances.refetch} />}
    </Panel>
    <Panel title={'transactions'}>
      {search.account && <Row><Button onClick={() => change({ account: undefined, page: undefined })}>{t(key('clearAccount'))}</Button></Row>}
      {transactions.isPending || transactions.isError ? <RuntimeState error={transactions.error} retry={transactions.refetch} /> : transactions.data.items.length ?
        <Columns label={'transactions'} names={['posted', 'description', 'reference', 'status', 'actions']} rows={transactions.data.items.map(tx => ({
          id: tx.id, cells: [date(tx.posted_at), data(t, tx.description), data(t, tx.reference),
            enumLabel(t, tx.reverses_id ? 'reversal' : tx.reversed_by_id ? 'reversed' : 'posted'),
            <Button onClick={() => change({ view: search.view === tx.id ? undefined : tx.id })}>{t(key(search.view === tx.id ? 'hideEntries' : 'showEntries'))}</Button>],
        }))} /> : <Empty message="noTransactions" onAction={transactions.refetch} />}
      <Pager label={'transactions'} page={page} size={size} total={transactions.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.view && <Panel title={'transaction'}>
      <Row><Button onClick={() => change({ view: undefined })}>{t(key('close'))}</Button></Row>
      {detail.isPending || detail.isError ? <RuntimeState error={detail.error} retry={detail.refetch} /> : <Stack>
        <Details values={[[ 'description', data(t, detail.data.description)], ['postedBy', data(t, detail.data.posted_by)], ['idempotency', data(t, detail.data.idempotency_key)]]} />
        <Row>{[detail.data.reverses_id, detail.data.reversed_by_id].filter((id): id is string => !!id).map(id =>
          <Button key={id} onClick={() => change({ view: id })}>{t(key('relatedTransaction'))}</Button>)}</Row>
        <Columns label={'entries'} names={['line', 'account', 'currency', 'debit', 'credit']} rows={detail.data.entries.map(e => ({
          id: e.id, cells: [data(t, e.line_no), data(t, postingAccounts.find(a => a.id === e.account_id)?.name ?? e.account_id), data(t, e.currency),
            e.direction === 'debit' ? money(e.amount_minor, e.currency) : data(t, null), e.direction === 'credit' ? money(e.amount_minor, e.currency) : data(t, null)],
        }))} />
        {writable && !detail.data.reversed_by_id && !detail.data.reverses_id && !idempotencyIssue(detail.data.idempotency_key) &&
          <Reverse key={detail.data.id} session={session} id={detail.data.id} reload={detail.refetch} />}
      </Stack>}
    </Panel>}
    {requestsAllAccounts && (allAccounts.isPending || allAccounts.isError) && <RuntimeState error={allAccounts.error} retry={allAccounts.refetch} />}
    {allAccounts.data?.truncated && <Alert tone="warning">{t(key('listTruncated'))}</Alert>}
    {writable && !!postingAccounts.length && <PostTransaction session={session} accounts={postingAccounts} reload={refresh} />}
  </Stack>
}

type AccountInput = Pick<Account, 'name' | 'code' | 'kind' | 'currency'>
function CreateAccount({ session }: { session: Session }) {
  const t = useT()
  const mutation = useRuntimeWrite<AccountInput, Account>(session, accountsPath)
  return <Stack>
    <Form fields={[field(t, 'code', { max: 64, required: true, validate: accountCodeIssue }), field(t, 'name', { max: 200, required: true }),
      selectField(t, 'kind', choices(t, kinds, 'choose'), 'asset'), field(t, 'currency', { max: 3, required: true, validate: currencyIssue })]}
    serverErrors={serverFields(mutation.error)} pending={mutation.isPending} submitLabel={t(key('createAccount'))} onSubmit={form => mutation.mutate({
      code: text(form, 'code'), name: text(form, 'name'), kind: text(form, 'kind'), currency: text(form, 'currency').toUpperCase(),
    })} />
    <WriteStatus error={mutation.error} reload={mutation.reset} success={mutation.isSuccess ? t(key('accountCreated')) : undefined} />
  </Stack>
}
type TransactionInput = { idempotency_key: string; description?: string; reference?: string; entries: { account_id: string; amount_minor: number }[] }
function PostTransaction({ session, accounts, reload }: { session: Session; accounts: Account[]; reload: () => unknown }) {
  const t = useT()
  const [idempotency, setIdempotency] = useState(newIdempotencyKey)
  const [count, setCount] = useState(2)
  const [error, setError] = useState('')
  const mutation = useRuntimeWrite<TransactionInput, Transaction>(session, transactionPath)
  const options = [{ value: '_none', label: t(key('choose')) }, ...accounts.map(a => ({ value: a.id, label: t(key('accountItem'), { code: a.code, name: a.name }) }))]
  const indexes = Array.from({ length: count }, (_, i) => i)
  return <Panel title={'postTransaction'}>
    <Form key={idempotency} fields={[
      field(t, 'idempotency', { value: idempotency, max: 128, required: true, validate: idempotencyIssue }),
      field(t, 'description', { max: 500 }), field(t, 'reference', { max: 128 }),
      ...indexes.flatMap(i => [
        { ...selectField(t, 'account', options), name: 'account' + i, label: t(key('entryAccount'), { line: i + 1 }) },
        { ...selectField(t, 'side', choices(t, ['debit', 'credit'], 'choose'), i === 0 ? 'debit' : 'credit'), name: 'side' + i, label: t(key('entrySide'), { line: i + 1 }) },
        { ...field(t, 'amount', { required: true, max: 24, validate: (value, form) =>
          amountIssue(value, accounts.find(a => a.id === text(form, 'account' + i))?.exponent ?? 2, true) }),
          name: 'amount' + i, label: t(key('entryAmount'), { line: i + 1 }) },
      ]),
    ]} serverErrors={serverFields(mutation.error, { idempotency_key: 'idempotency' }, path => {
      const entry = /^entries\.(\d+)\.(account_id|amount_minor)$/.exec(path)
      return entry ? (entry[2] === 'account_id' ? 'account' : 'amount') + entry[1] : undefined
    })} formError={error || undefined} pending={mutation.isPending} submitLabel={t(key('postTransaction'))}
    actions={<><Button disabled={count >= 1000 || mutation.isPending} onClick={() => setCount(count + 1)}>{t(key('addEntry'))}</Button>
      <Button disabled={count <= 2 || mutation.isPending} onClick={() => setCount(count - 1)}>{t(key('removeEntry'))}</Button></>}
    onSubmit={form => {
      const totals = new Map<string, bigint>()
      const entries = indexes.map(i => {
        const account = accounts.find(a => a.id === text(form, 'account' + i))
        const value = parseMajor(text(form, 'amount' + i), account?.exponent ?? 2) ?? 0n
        const amount = text(form, 'side' + i) === 'debit' ? value : -value
        if (account) totals.set(account.currency, (totals.get(account.currency) ?? 0n) + amount)
        return { account_id: account?.id ?? '', amount_minor: Number(amount) }
      })
      if (entries.some(e => !e.account_id)) { setError(t(key('chooseAccount'))); return }
      if ([...totals.values()].some(total => total !== 0n)) { setError(t(key('transactionUnbalanced'))); return }
      setError('')
      mutation.mutate({ entries, idempotency_key: text(form, 'idempotency'), description: optional(form, 'description'), reference: optional(form, 'reference') },
        { onSuccess: () => { setCount(2); setIdempotency(newIdempotencyKey()) } })
    }} />
    <WriteStatus error={mutation.error} reload={reload} replayed={mutation.data?.replayed} success={mutation.isSuccess ? t(key('transactionPosted')) : undefined} />
  </Panel>
}
function Reverse({ session, id, reload }: { session: Session; id: string; reload: () => unknown }) {
  const t = useT()
  const [idempotency] = useState(newIdempotencyKey)
  const [description, setDescription] = useState('')
  const mutation = useRuntimeWrite<{ idempotency_key: string; description?: string }, Transaction>(session, `/ledger/transactions/${segment(id)}/reverse`)
  return <Stack>
    <Row><ConfirmDestructive trigger={<Button variant="danger">{t(key('reverse'))}</Button>} title={t(key('reverse'))} description={t(key('reverseHelp'))}
      action={t(key('reverseYes'))} pending={mutation.isPending} onConfirm={async () => {
        await mutation.mutateAsync({ idempotency_key: idempotency, description: description.trim() || undefined })
      }}>
      <Field label={t(key('description'))}>{attrs => <Input {...attrs} maxLength={500} value={description} onChange={event => setDescription(event.target.value)} />}</Field>
    </ConfirmDestructive></Row>
    <WriteStatus error={mutation.error} reload={reload} />
  </Stack>
}
