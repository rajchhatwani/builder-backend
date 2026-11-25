import { useState } from 'react'
import type { ComponentProps } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../../i18n'
import { ConfirmDestructive, Form, ReadOnlyNote, SettingsSection } from '../../../../patterns'
import { Button, Checkbox, Input, Row, Stack } from '../../../../ui'
import { orgAiBudget, orgAiKey, orgApprovalHours, orgLimits, orgUsageLimit, validators } from '../../../../validators'
import { orgApi, orgQueries } from '../../api/org'
import type { OrgAiSettings, OrgAiSettingsWrite, OrgUsageMetric } from '../../api/org'
import { money, orgDate, OrgData, orgFieldError, OrgPager, OrgProblem, OrgTable, textValue, useOrgAction, useOrgFields } from './shared'
import type { OrgProps } from './shared'

const gates = ['A', 'B', 'C', 'D', 'E'] as const
type Gate = typeof gates[number]
type ApprovalPolicy = {
  ttl_hours?: number
  ttl_plan_hours?: number
  roles?: Partial<Record<Gate, 'owner'>>
  auto_plan_small_edit?: false
  separation_of_duties?: true
}

function ApprovalSettings({ settings, ...props }: OrgProps & { settings: OrgAiSettings }) {
  const t = useT()
  const action = useOrgAction(props)
  const fields = useOrgFields()
  const current = settings.approval_policy
  const initialRoles = current?.roles as ApprovalPolicy['roles']
  const save = (approval_policy: ApprovalPolicy) => {
    const body: OrgAiSettingsWrite & { approval_policy: ApprovalPolicy } = { approval_policy }
    return orgApi.aiSettings(props.org.slug, body)
  }
  return <SettingsSection title={t('org.approvalPolicy')} description={t('org.approvalHelp')}>
    {action.isError && <OrgProblem error={action.error} />}
    <Form key={JSON.stringify(current)} fields={[
      fields.input('approvalHours', { defaultValue: typeof current?.ttl_hours === 'number' ? current.ttl_hours : '', inputMode: 'numeric' }, [orgApprovalHours]),
      fields.input('planHours', { defaultValue: typeof current?.ttl_plan_hours === 'number' ? current.ttl_plan_hours : '', inputMode: 'numeric' }, [orgApprovalHours]),
    ]} pending={action.isPending} submitLabel={t('common.save')} onSubmit={data => {
      const ttl = textValue(data, 'approvalHours')
      const plan = textValue(data, 'planHours')
      const roles = Object.fromEntries(gates.filter(gate => data.has(gate)).map(gate => [gate, 'owner' as const]))
      action.submit(() => save({
        ttl_hours: ttl ? Number(ttl) : undefined, ttl_plan_hours: plan ? Number(plan) : undefined,
        roles: Object.keys(roles).length ? roles : undefined,
        auto_plan_small_edit: data.has('noAutoPlan') ? false : undefined,
        separation_of_duties: data.has('separateApprovers') ? true : undefined,
      }))
    }}>
      <fieldset><legend>{t('org.ownerApproval')}</legend>
        <Row>{gates.map(gate => <Checkbox key={gate} name={gate} defaultChecked={initialRoles?.[gate] === 'owner'}
          disabled={action.isPending} label={t('org.approvalGate', { gate })} />)}</Row>
      </fieldset>
      <Checkbox name="noAutoPlan" label={t('org.noAutoPlan')} defaultChecked={current?.auto_plan_small_edit === false} disabled={action.isPending} />
      <Checkbox name="separateApprovers" label={t('org.separateApprovers')} defaultChecked={current?.separation_of_duties === true} disabled={action.isPending} />
    </Form>
    {current && <Row><ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending}>{t('org.resetApprovals')}</Button>}
      title={t('org.resetApprovals')} description={t('org.resetApprovalsBody')} action={t('org.resetApprovals')}
      onConfirm={() => action.perform(() => save({}))} /></Row>}
  </SettingsSection>
}

function AiSettings({ settings, ...props }: OrgProps & { settings: OrgAiSettings }) {
  const t = useT()
  const fields = useOrgFields()
  const action = useOrgAction(props)
  const [revision, reset] = useState(0)
  const serverErrors = orgFieldError(action.error, { api_key: 'aiKey', monthly_budget_micro_usd: 'budget' })
  function clear(body: OrgAiSettingsWrite) {
    return action.perform(async () => {
      await orgApi.aiSettings(props.org.slug, body)
      reset(value => value + 1)
    }, 'org.aiSaved')
  }
  return <SettingsSection title={t('org.aiSettings')}>
    <p data-testid="ai-key-state">{t(settings.has_api_key ? 'org.ownKey' : 'org.platformKey', { hint: settings.api_key_hint ?? '' })}</p>
    {action.isError && <div data-testid="ai-error"><OrgProblem error={action.error} /></div>}
    {action.isSuccess && <p role="status" data-testid="ai-saved">{t('org.aiSaved')}</p>}
    <Form key={revision + ":" + settings.monthly_budget_micro_usd} serverErrors={serverErrors} pending={action.isPending} fields={[
      fields.input('aiKey', { type: 'password', autoComplete: 'off', maxLength: orgLimits.aiKey, placeholder: t('org.keyPlaceholder'), 'data-testid': 'ai-key' }, [validators.length(orgLimits.aiKey), orgAiKey]),
      fields.input('budget', { inputMode: 'decimal', defaultValue: settings.monthly_budget_micro_usd != null ? String(settings.monthly_budget_micro_usd / 1_000_000) : '', 'data-testid': 'ai-budget' }, [orgAiBudget]),
    ]} submitLabel={t('common.save')} submitProps={{ 'data-testid': 'ai-save' }} onSubmit={data => {
      const api_key = textValue(data, 'aiKey')
      const budget = textValue(data, 'budget')
      const monthly_budget_micro_usd = budget ? Math.round(Number(budget) * 1_000_000) : undefined
      if (!api_key && monthly_budget_micro_usd === undefined) return
      action.submit(async () => {
        await orgApi.aiSettings(props.org.slug, { api_key: api_key || undefined, monthly_budget_micro_usd })
        reset(value => value + 1)
      }, 'org.aiSaved')
    }} />
    <Row>
      {settings.has_api_key && <ConfirmDestructive trigger={<Button data-testid="ai-clear-key" variant="danger" disabled={action.isPending}>{t('org.removeKey')}</Button>}
        title={t('org.removeKey')} description={t('org.removeKeyBody')} action={t('org.removeKey')} onConfirm={() => clear({ clear_api_key: true })} />}
      {settings.monthly_budget_micro_usd != null && <ConfirmDestructive trigger={<Button data-testid="ai-clear-budget" variant="danger" disabled={action.isPending}>{t('org.removeBudget')}</Button>}
        title={t('org.removeBudget')} description={t('org.removeBudgetBody')} action={t('org.removeBudget')} onConfirm={() => clear({ clear_budget: true })} />}
    </Row>
  </SettingsSection>
}

export function Ai(props: OrgProps) {
  const { org, search, setSearch } = props
  const t = useT()
  const page = search.page ?? 1
  const settings = useQuery(orgQueries.aiSettings(org.slug))
  const cost = useQuery(orgQueries.aiCost(org.slug, page))
  const label = t('org.aiLedger')
  return <Stack gap={4}>
    <OrgData query={settings}>{data => <>
      <AiSettings {...props} settings={data} />
      <ApprovalSettings {...props} settings={data} />
    </>}</OrgData>
    <OrgData query={cost}>{data => <>
      <SettingsSection title={t('org.spend')}>
        <p data-testid="ai-cost-month">{t('org.spendSummary', {
          month: money(data.month_cost_micro_usd / 1_000_000), total: money(data.total_cost_micro_usd / 1_000_000),
          budget: data.monthly_budget_micro_usd == null ? t('org.noBudget') : money(data.monthly_budget_micro_usd / 1_000_000),
        })}</p>
      </SettingsSection>
      <div data-testid="ai-cost"><SettingsSection title={label}>
        <OrgTable label={label} fields={['when', 'model', 'task', 'inputTokens', 'outputTokens', 'cacheRead', 'cacheWrite', 'projectId', 'runId', 'cost']}
          empty={t('org.noCalls')} action={<Button onClick={() => { if (page > 1) setSearch({ tab: 'ai' }); else void cost.refetch() }}>{t('common.reload')}</Button>}
          rows={data.items.map(row => ({ id: row.id, testId: 'ai-cost-row', cells: [
            orgDate(row.created_at), row.model, row.task_class, row.input_tokens, row.output_tokens,
            row.cache_read_tokens ?? t('org.na'), row.cache_write_tokens ?? t('org.na'), row.project_id ?? t('org.na'), row.run_id ?? t('org.na'),
            money(row.cost_micro_usd / 1_000_000),
          ].map(value => typeof value === 'number' ? t('org.number', { number: value }) : value) }))} />
        <OrgPager label={label} page={page} size={20} total={data.total} onChange={page => setSearch({ tab: 'ai', page })} />
      </SettingsSection></div>
    </>}</OrgData>
  </Stack>
}

function Limit({ metric, ...props }: OrgProps & { metric: OrgUsageMetric }) {
  const t = useT()
  const action = useOrgAction(props)
  const label = t('org.limitFor', { metric: metric.metric })
  return <Stack>
    {action.isError && <div data-testid="usage-error"><OrgProblem error={action.error} /></div>}
    <Form fields={[{ name: 'limit', label, validate: [validators.required, orgUsageLimit],
      control: attributes => <InputLimit {...attributes} value={metric.limit} /> }]} pending={action.isPending}
      submitLabel={t('common.save')} submitProps={{ 'data-testid': 'usage-save' }} onSubmit={data => {
        action.submit(() => orgApi.usageLimit(props.org.slug, metric.metric, Number(textValue(data, 'limit'))))
      }} actions={metric.limit != null && <ConfirmDestructive
        trigger={<Button data-testid="usage-clear" variant="danger" disabled={action.isPending}>{t('org.noLimit')}</Button>}
        title={label} description={t('org.clearLimitBody')} action={t('org.noLimit')}
        onConfirm={() => action.perform(() => orgApi.usageLimit(props.org.slug, metric.metric, null))} />} />
  </Stack>
}


function InputLimit({ value, ...attributes }: Omit<ComponentProps<typeof Input>, 'value'> & { value: number | null }) {
  return <Input key={String(value)} {...attributes} defaultValue={value ?? ''} inputMode="numeric" data-testid="usage-edit" />
}

export function Usage(props: OrgProps) {
  const { org } = props
  const t = useT()
  const query = useQuery(orgQueries.usage(org.slug))
  const owner = org.my_role === 'owner'
  const number = (value: number) => t('org.number', { number: value })
  return <OrgData query={query}>{data => <SettingsSection title={t('org.tab.usage')}>
    {!owner && <ReadOnlyNote>{t('org.usageReadOnly')}</ReadOnlyNote>}
    <div data-testid={data.metrics.length ? 'usage-table' : 'usage-empty'}>
      <OrgTable label={t('org.tab.usage')} fields={['metric', 'period', 'start', 'end', 'used', 'limit', 'refused', ...(owner ? ['changeLimit'] : [])]}
        empty={t('org.noUsage')} action={<Button onClick={() => void query.refetch()}>{t('common.reload')}</Button>}
        rows={data.metrics.map(metric => ({ id: metric.metric, testId: 'usage-row', cells: [
          t('org.metricWithUnit', { metric: metric.metric, unit: metric.unit }), t('org.period.' + metric.period),
          orgDate(metric.period_start) ?? t('org.na'), orgDate(metric.period_end) ?? t('org.na'),
          <span data-testid="usage-used">{number(metric.used)}</span>,
          <span data-testid="usage-limit">{metric.limit == null ? t('org.noLimit') : number(metric.limit)}</span>,
          <span data-testid="usage-refused">{number(metric.refused)}</span>,
          owner && <Limit {...props} metric={metric} />,
        ] }))} />
    </div>
  </SettingsSection>}</OrgData>
}
