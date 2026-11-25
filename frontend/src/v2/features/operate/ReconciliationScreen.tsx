import { useState } from 'react'
import type { Account } from '../../../shell/ledger/ledgerLogic'
import { defaultExponent, newIdempotencyKey, parseStatementCsv } from '../../../shell/money/moneyLogic'
import type { StatementLine } from '../../../shell/money/moneyLogic'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Alert, Button, Row, Stack } from '../../ui'
import { segment, useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import type { Match, Results, Run, RunInput } from './api/money'
import { canWrite } from './api/operate'
import { SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { LedgerLink, useMoney } from './components/Money'
import { choices, Columns, data, Details, Empty, enumLabel, field, key, optional, Pager, Panel, Pick, Refresh,
  RuntimeScreen, RuntimeState, selectField, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'

const runsPath = '/reconciliation/runs'
const runPath = (id: string) => `/reconciliation/runs/${segment(id)}` as const
const size = 100
export default function ReconciliationScreen(props: LiveProps) {
  return <RuntimeScreen id={props} title={'reconciliation'}>{session => <Reconciliation session={session} writable={canWrite(props)} />}</RuntimeScreen>
}
function Reconciliation({ session, writable }: { session: Session; writable: boolean }) {
  const { search, change } = useOperateSearch()
  const t = useT()
  const money = useMoney()
  const date = useOperateDate()
  const page = search.page ?? 1
  const list = useRuntimeQuery<Page<Run>>(session, runsPath, { limit: size, offset: (page - 1) * size, status: search.status })
  const accounts = useRuntimeQuery<Page<Account>>(session, '/ledger/accounts', { limit: 200 }, writable)
  const [start, setStart] = useState(false)
  return <Stack gap={4}>
    <Row><Refresh run={() => Promise.all([list.refetch(), ...(writable ? [accounts.refetch()] : [])])} />
      <SectionLink id={session.projectId} section="reconsettings" label={t(key('reconSettings'))} />
      <SectionLink id={session.projectId} section="ledger" label={t(key('ledger'))} />
      {writable && <Button onClick={() => setStart(!start)}>{t(key(start ? 'close' : 'importStatement'))}</Button>}</Row>
    <Panel title={'runs'}>
      <Row><Pick label={t(key('status'))} value={search.status ?? ''} options={choices(t, ['open', 'closed'])}
        onChange={status => change({ status: status || undefined, page: undefined })} /></Row>
      {list.isPending || list.isError ? <RuntimeState error={list.error} retry={list.refetch} /> : list.data.items.length ?
        <Columns label={'runs'} names={['name', 'period', 'currency', 'status', 'matched', 'created', 'closedAt', 'difference', 'actions']} rows={list.data.items.map(r => ({
          id: r.id, cells: [data(t, r.name ?? r.id), t(key('periodValue'), { start: data(t, r.period_start), end: data(t, r.period_end) }), data(t, r.currency),
            enumLabel(t, r.status), t(key('matchedCount'), { matched: r.matched_count, total: r.line_count }), date(r.created_at), date(r.closed_at),
            r.summary ? money(r.summary.difference_minor, r.currency) : data(t, null),
            <Button aria-label={t(key('openRun'), { name: r.name ?? r.id })} onClick={() => change({ view: r.id, matchPage: undefined })}>{t(key('open'))}</Button>],
        }))} /> : <Empty message="noRuns" action={writable ? 'importStatement' : undefined} onAction={writable ? () => setStart(true) : list.refetch} />}
      <Pager label={'runs'} size={size} page={page} total={list.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.view && <RunDetails key={search.view} session={session} id={search.view} writable={writable} />}
    {writable && start && <Panel title={'importStatement'}>
      {accounts.isPending ? <RuntimeState retry={accounts.refetch} /> : <>
        {accounts.isError && <RuntimeState error={accounts.error} retry={accounts.refetch} />}
        <ImportStatement session={session} accounts={accounts.data?.items ?? []} onSave={id => { change({ view: id, matchPage: undefined }); setStart(false) }} />
      </>}
    </Panel>}
  </Stack>
}
function ImportStatement({ session, accounts, onSave }: { session: Session; accounts: Account[]; onSave: (id: string) => void }) {
  const t = useT()
  const [keyValue] = useState(newIdempotencyKey)
  const mutation = useRuntimeWrite<RunInput, Run>(session, runsPath)
  const fields = [
    accounts.length ? selectField(t, 'account', accounts.map(a => ({ value: a.id, label: t(key('accountItem'), { code: a.code, name: a.name }) }))) :
      field(t, 'account', { required: true, max: 36 }),
    ...(!accounts.length ? [field(t, 'currency', { required: true, max: 3 })] : []),
    field(t, 'name', { max: 200 }), field(t, 'periodStart', { type: 'date' }),
    field(t, 'periodEnd', { type: 'date', validate: (v, form) => v && v < text(form, 'periodStart') ? { key: key('periodError') } : undefined }),
    field(t, 'idempotency', { value: keyValue, required: true, max: 128 }),
  ]
  const csv = (value: string, form: FormData) => {
    const account = accounts.find(a => a.id === text(form, 'account'))
    const currency = account?.currency ?? text(form, 'currency').toUpperCase()
    return parseStatementCsv(value, account?.exponent ?? defaultExponent(currency), currency)
  }
  return <Stack>
    <Form fields={[...fields, { ...field(t, 'statement', { area: true, validate: (v, form) => {
      const parsed = csv(v, form)
      return parsed.error ? { key: key('value'), values: { value: parsed.error } } : undefined
    } }), hint: t(key('csvHelp')) }]} serverErrors={serverFields(mutation.error, {
      account_id: 'account', period_start: 'periodStart', period_end: 'periodEnd', idempotency_key: 'idempotency',
    }, path => path.startsWith('lines') ? 'statement' : undefined)} submitLabel={t(key('importRun'))} pending={mutation.isPending} onSubmit={form => {
      const parsed = csv(text(form, 'statement'), form)
      if (parsed.lines) mutation.mutate({ account_id: text(form, 'account'), name: optional(form, 'name'),
        period_start: optional(form, 'periodStart'), period_end: optional(form, 'periodEnd'), idempotency_key: text(form, 'idempotency'), lines: parsed.lines },
      { onSuccess: reply => onSave(reply.data.id) })
    }} />
    <WriteStatus error={mutation.error} reload={mutation.reset} />
  </Stack>
}
function RunDetails({ session, id, writable }: { session: Session; id: string; writable: boolean }) {
  const t = useT()
  const date = useOperateDate()
  const money = useMoney()
  const { search, change } = useOperateSearch()
  const page = search.matchPage ?? 1
  const path = runPath(id)
  const run = useRuntimeQuery<Run>(session, path)
  const result = useRuntimeQuery<Results>(session, `${path}/results`, { limit: 200, offset: (page - 1) * 200 })
  const reload = () => Promise.all([run.refetch(), result.refetch()])
  const value = result.data
  return <Panel title={'runDetails'}>
    <Row><Button onClick={() => change({ view: undefined, matchPage: undefined })}>{t(key('close'))}</Button><Refresh run={reload} /></Row>
    {run.isPending || run.isError || result.isPending || result.isError || !value ? <RuntimeState error={run.error ?? result.error} retry={reload} /> : <Stack>
      <Details values={[['name', data(t, run.data.name)], ['status', enumLabel(t, run.data.status)], ['account', data(t, run.data.account_id)],
        ...Object.entries(value.summary).flatMap(([label, amount]): [string, string][] => label.endsWith('_minor') ? [[label, money(amount, run.data.currency)]] : [])]} />
      {value.entries_truncated && <Alert tone="warning">{t(key('entriesTruncated'))}</Alert>}
      <h3>{t(key('matched'))}</h3>
      <Columns label={'matched'} names={['statement', 'entry', 'method', 'difference', 'matchedAt', 'actions']} rows={value.matched.map(({ line, entry, match }) => ({
        id: match.id, cells: [data(t, line.external_id), <LedgerLink projectId={session.projectId} id={entry.transaction_id} />,
          enumLabel(t, match.method), money(match.diff_minor, run.data.currency), date(match.matched_at),
          writable && run.data.status === 'open' ? <Unmatch session={session} run={id} id={match.id} reload={reload} /> : data(t, null)],
      }))} />
      <Pager label={'matched'} page={page} size={200} total={value.matched_total} change={matchPage => change({ matchPage })} />
      <h3>{t(key('unmatchedLines'))}</h3>
      <Columns label={'unmatchedLines'} names={['externalId', 'date', 'reference', 'amount']} rows={value.unmatched_lines.map(line => ({
        id: line.id, cells: [data(t, line.external_id), data(t, line.date), data(t, line.reference), money(line.amount_minor, run.data.currency)],
      }))} />
      <h3>{t(key('unmatchedEntries'))}</h3>
      <Columns label={'unmatchedEntries'} names={['date', 'description', 'amount', 'transaction']} rows={value.unmatched_entries.map(entry => ({
        id: entry.id, cells: [data(t, entry.date), data(t, entry.description ?? entry.reference), money(entry.amount_minor, run.data.currency),
          <LedgerLink projectId={session.projectId} id={entry.transaction_id} />],
      }))} />
      {writable && run.data.status === 'open' && <RunActions session={session} results={value} reload={reload} />}
    </Stack>}
  </Panel>
}
function Unmatch({ session, run, id, reload }: { session: Session; run: string; id: string; reload: () => unknown }) {
  const t = useT()
  const mutation = useRuntimeWrite<undefined, Match>(session, `${runPath(run)}/matches/${segment(id)}`, 'DELETE')
  return <Stack><ConfirmDestructive trigger={<Button variant="danger">{t(key('unmatch'))}</Button>} title={t(key('unmatch'))}
    description={t(key('unmatchHelp'))} action={t(key('unmatch'))} pending={mutation.isPending}
    onConfirm={async () => { await mutation.mutateAsync(undefined) }} />
    <WriteStatus error={mutation.error} reload={reload} /></Stack>
}
function RunActions({ session, results, reload }: { session: Session; results: Results; reload: () => unknown }) {
  const t = useT()
  const path = runPath(results.run.id)
  const [addVersion, setAddVersion] = useState(0)
  const auto = useRuntimeWrite<undefined, { new_matches: number }>(session, `${path}/match`)
  const manual = useRuntimeWrite<{ line_id: string; entry_id: string }, Match>(session, `${path}/matches`)
  const add = useRuntimeWrite<{ lines: StatementLine[] }, { added: number; skipped: number }>(session, `${path}/lines`)
  const close = useRuntimeWrite<undefined, Run>(session, `${path}/close`)
  const currency = results.run.currency
  const csv = (value: string) => parseStatementCsv(value, defaultExponent(currency), currency)
  return <Stack>
    <Row><Button disabled={auto.isPending} onClick={() => auto.mutate(undefined)}>{t(key('autoMatch'))}</Button>
      <ConfirmDestructive trigger={<Button variant="danger" disabled={results.entries_truncated}>{t(key('closeRun'))}</Button>} title={t(key('closeRun'))}
        description={t(key('closeRunHelp'))} action={t(key('closeRunYes'))} pending={close.isPending}
        onConfirm={async () => { await close.mutateAsync(undefined) }} />
    </Row>
    <WriteStatus error={auto.error ?? close.error} reload={reload} success={auto.data ? t(key('autoMatched'), { count: auto.data.data.new_matches }) : undefined} />
    {!!results.unmatched_lines.length && !!results.unmatched_entries.length && <Form fields={[
      selectField(t, 'statementLine', results.unmatched_lines.map(line => ({ value: line.id, label: data(t, line.external_id) }))),
      selectField(t, 'entry', results.unmatched_entries.map(entry => ({ value: entry.id, label: t(key('entryItem'), { date: entry.date, name: entry.description ?? entry.reference ?? entry.id }) }))),
    ]} submitLabel={t(key('match'))} pending={manual.isPending} onSubmit={form => manual.mutate({
      line_id: text(form, 'statementLine'), entry_id: text(form, 'entry'),
    })} />}
    <WriteStatus error={manual.error} reload={reload} success={manual.isSuccess ? t(key('matchSaved')) : undefined} />
    <Form key={addVersion} fields={[{ ...field(t, 'statement', { area: true, validate: v => {
      const error = csv(v).error
      return error ? { key: key('value'), values: { value: error } } : undefined
    } }), hint: t(key('csvHelp')) }]} serverErrors={serverFields(add.error, {}, path => path.startsWith('lines') ? 'statement' : undefined)}
      submitLabel={t(key('addLines'))} pending={add.isPending} onSubmit={form => {
      const lines = csv(text(form, 'statement')).lines
      if (lines) add.mutate({ lines }, { onSuccess: () => setAddVersion(v => v + 1) })
    }} />
    <WriteStatus error={add.error} reload={reload} success={add.data ? t(key('linesAdded'), add.data.data) : undefined} />
  </Stack>
}
