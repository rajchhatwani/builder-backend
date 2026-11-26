import { useQuery } from '@tanstack/react-query'
import { useRef } from 'react'
import { useLanguage, useT } from '../../i18n'
import { Form } from '../../patterns'
import { Alert, Badge, Button, Disclosure, Grid, Input, Progress, Row, Select, Stack, Field } from '../../ui'
import { noNullIssue, uuidIssue } from '../../validators/operateRuntime'
import { toBig } from '../../../shell/money/moneyLogic'
import { usd } from '../../../shell/aipack/aiLogic'
import { callsOptions, callStatuses, usageOptions } from './api/ai'
import type { Usage } from './api/ai'
import type { LiveProps, Session } from './api/live'
import { AiActions, AiFeedback, AiRuntime, useAiFormat } from './components/AiRuntime'
import { useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Empty, enumLabel, key, optional, Pager, Panel } from './components/Runtime'

export default function AiUsageScreen(props: LiveProps) {
  return <AiRuntime id={props} title={'aiusage'}>{session => <UsagePage session={session} />}</AiRuntime>
}

function UsagePage({ session }: { session: Session }) {
  const t = useT()
  const date = useOperateDate()
  const format = useAiFormat()
  const { search, change } = useOperateSearch()
  const filters = useRef<HTMLInputElement>(null)
  const size = 50
  const page = search.page ?? 1
  const usage = useQuery(usageOptions(session))
  const status = callStatuses.find(status => search.status === status)
  const callerIssue = search.caller ? uuidIssue(search.caller) : undefined
  const calls = useQuery(callsOptions(session, {
    limit: size, offset: (page - 1) * size, stage: search.stage, status,
    caller_id: search.caller,
  }, !callerIssue))
  const clear = () => change({ stage: undefined, caller: undefined, status: undefined, page: undefined })
  const filtered = Boolean(search.stage || search.caller || status)
  return <Stack gap={4}>
    <AiActions id={session.projectId} settings="aigatewaysettings" testId="usage-refresh"
      refresh={() => Promise.all([usage.refetch(), ...(!callerIssue ? [calls.refetch()] : [])])} />
    <p className="v2-muted" data-testid="usage-estimate-note">{t(key('usageEstimate'))}</p>
    <Panel title={'usageBudget'}>
      {usage.data ? <UsageTotals usage={usage.data} /> : <AiFeedback error={usage.error} retry={usage.refetch} />}
      {usage.data && usage.isError && <AiFeedback error={usage.error} retry={usage.refetch} />}
    </Panel>
    <Panel title={'calls'}>
      <Form key={JSON.stringify([search.stage, search.caller])} fields={[
        { name: 'stage', label: t(key('stage')), hint: t(key('exactStage')), validateWith: noNullIssue,
          control: attrs => <Input {...attrs} ref={filters} maxLength={40} defaultValue={search.stage} data-testid="calls-stage" /> },
        { name: 'caller', label: t(key('callerId')), hint: t(key('callerHint')),
          validateWith: value => value.trim() ? uuidIssue(value) : undefined,
          control: attrs => <Input {...attrs} maxLength={36} defaultValue={search.caller} data-testid="calls-caller" /> },
      ]} layout={fields => <Grid>{fields.stage}
        <Field label={t(key('status'))}>{attrs => <Select triggerProps={{ ...attrs, 'data-testid': 'calls-status' }}
          options={choices(t, callStatuses, 'allStatuses')} value={status ?? '_none'}
          onValueChange={status => {
            const form = filters.current?.form
            const values = form && new FormData(form)
            const caller = values ? optional(values, 'caller') : search.caller
            if (caller && uuidIssue(caller)) {
              form?.requestSubmit()
              return
            }
            const stage = values ? optional(values, 'stage') : search.stage
            change({ stage, caller, status: status === '_none' ? undefined : status, page: undefined })
          }} />}</Field>
        {fields.caller}</Grid>}
        submitLabel={t(key('apply'))} onSubmit={form => change({ stage: optional(form, 'stage'), caller: optional(form, 'caller'), page: undefined })}
        actions={filtered && <Button onClick={clear}>{t(key('clearFilters'))}</Button>} />
      {callerIssue ? <Alert tone="warning">{t(callerIssue.key)}</Alert> :
        calls.isPending || calls.isError ? <AiFeedback error={calls.error} retry={calls.refetch} /> :
        calls.data.items.length ? <Columns label={'callHistory'} names={['created', 'stage', 'status', 'providerModel', 'aiTokens', 'estimatedCost', 'callerId', 'errorCode']}
          rows={calls.data.items.map(call => ({ id: call.id, testId: 'calls-row', cells: [
            date(call.created_at), data(t, call.stage),
            <Badge tone={call.status === 'error' ? 'danger' : call.status === 'ok' ? 'success' : 'neutral'}>{enumLabel(t, call.status)}</Badge>,
            t(key(call.fallback_used ? 'fallbackModel' : 'modelName'), { provider: call.provider, model: call.model }),
            format.pair(call.input_tokens, call.output_tokens), t(key('usd'), { amount: usd(call.cost_micro_usd) }),
            call.caller_id ? <Disclosure label={t(key('showId'))}>{data(t, call.caller_id)}</Disclosure> : data(t, null),
            data(t, call.error_code),
          ] }))} /> :
          <Empty message={filtered ? 'noCallsMatch' : 'noCalls'} action={filtered ? 'clearFilters' : 'refresh'}
            onAction={filtered ? clear : calls.refetch} />}
      <Pager label={'callHistory'} page={page} total={calls.data?.total ?? 0} size={size} change={page => change({ page })} />
    </Panel>
  </Stack>
}

function UsageTotals({ usage }: { usage: Usage }) {
  const t = useT()
  const { language } = useLanguage()
  const start = new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(usage.period_start))
  const format = useAiFormat()
  const limit = toBig(usage.limit_micro_usd)
  const held = toBig(usage.spent_micro_usd) + toBig(usage.reserved_micro_usd)
  const used = limit > 0n ? Math.min(100, Number(held * 100n / limit)) : 0
  const money = (amount: string | number) => t(key('usd'), { amount: usd(amount) })
  const totals = [
    ['budgetEstimate', money(usage.limit_micro_usd), 'usage-limit'],
    ['spentEstimate', money(usage.spent_micro_usd), 'usage-spent'],
    ['reservedEstimate', money(usage.reserved_micro_usd), 'usage-reserved'],
    ['remainingEstimate', money(usage.remaining_micro_usd), 'usage-remaining'],
    ['aiCallCounts', format.pair(usage.calls_ok, usage.calls_error), 'usage-calls'],
    ['aiTokens', format.pair(usage.input_tokens, usage.output_tokens), 'usage-tokens'],
  ]
  return <Stack>
    <p>{t(key('usagePeriod'), { period: enumLabel(t, usage.period), start, region: usage.region })}
      {' '}{t(key(usage.zero_retention ? 'zeroRetention' : 'retention'))}</p>
    <dl className="v2-grid v2-ai-list">{totals.map(([label, value, testId]) => <Stack key={label} gap={1}>
      <dt>{t(key(label))}</dt><dd data-testid={testId}><strong>{value}</strong></dd>
    </Stack>)}</dl>
    <Row><Progress value={used} max={100} label={t(key('budgetUsed'))} data-testid="usage-bar" />
      <span>{t(key('budgetProgress'), { percent: format.bp(used * 100) })}</span></Row>
  </Stack>
}
