import { useQuery } from '@tanstack/react-query'
import { useLanguage, useT } from '../../i18n'
import { SettingsSection } from '../../patterns'
import { Badge, CodeBlock, Disclosure, Grid, Progress, Row, Skeleton, Stack } from '../../ui'
import { connectCurrency, connectDistinct, connectLimits, connectList, connectRefund, connectUrls, validators } from '../../validators'
import { paymentsOptions, sizingOptions, usePaymentsWrite } from './api/connect'
import type { ConnectProps, PaymentsConfig, PaymentsSizing, PaymentsWrite } from './api/connect'
import { useFields } from './components/Fields'
import type { EditorProps, Group } from './components/Fields'
import { IssueList, RetryAlert, SettingsPage } from './components/SettingsPage'
import type { Model } from './components/SettingsPage'
import { checked, list, number, optionalNumber, text } from './state/draft'
import type { SettingsDraft } from './state/draft'

const roleActions = ['create', 'read', 'read_all', 'refund', 'approve_refund', 'operate'] as const
const statuses = ['status_pending', 'status_paid', 'status_partially_refunded', 'status_refunded'] as const
const roleDefaults = { create: [], read: [], read_all: [], refund: [], approve_refund: [], operate: [] }
export const paymentsDefaults: PaymentsWrite = {
  provider: 'stripe', payable: null, currencies: [], max_amount_minor: 10_000_000, success_urls: [], cancel_urls: [],
  roles: roleDefaults, refund_approval_threshold_minor: null,
  scale: {
    profile: 'small', peak_payments_per_minute: null, peak_webhooks_per_minute: null, db_max_connections: 100,
    availability: 'single', pgbouncer: false, kubernetes: false, webhook_mode: null, api_replicas: null, server_workers: null,
    worker_replicas: null, worker_concurrency: null, pool_size: null, webhook_events_retention_days: 90, jobs_retention_days: 30,
  },
  security: {
    webhook_tolerance_seconds: 300, webhook_max_body_bytes: 262_144, webhook_ip_allowlist_enabled: false,
    idempotency_ttl_hours: 48, audit_retention_days: 2555, secrets_from_files: true, allow_payer_edits: false,
  },
}

const zeroDecimal = ['CLP', 'JPY', 'KRW', 'PYG', 'RWF', 'VND', 'XAF', 'XOF', 'XPF']
const currencies = {
  stripe: ['AED', 'AUD', 'BGN', 'BRL', 'CAD', 'CHF', 'CZK', 'DKK', 'EUR', 'GBP', 'HKD', 'IDR', 'ILS', 'INR', 'MXN', 'MYR',
    'NOK', 'NZD', 'PHP', 'PLN', 'RON', 'SAR', 'SEK', 'SGD', 'THB', 'TRY', 'USD', 'ZAR', ...zeroDecimal].sort(),
  razorpay: ['AED', 'AUD', 'CAD', 'EUR', 'GBP', 'HKD', 'INR', 'SGD', 'USD'],
}
const simple = (values: readonly string[]) => values.map(value => ({ value, label: value }))
const currencyMode = (draft: SettingsDraft) => text(draft, 'currencyMode') || (text(draft, 'payable.currency_field') ? 'field' : 'fixed')

function toWrite(draft: SettingsDraft): PaymentsWrite {
  const entity = text(draft, 'payable.entity').trim()
  const fixed = currencyMode(draft) === 'fixed'
  return {
    provider: text(draft, 'provider') as PaymentsWrite['provider'],
    payable: !entity ? null : {
      entity,
      amount_field: text(draft, 'payable.amount_field').trim(),
      currency: fixed ? text(draft, 'payable.currency').trim() : null,
      currency_field: fixed ? null : text(draft, 'payable.currency_field').trim(),
      status_field: text(draft, 'payable.status_field').trim(),
      status_pending: text(draft, 'payable.status_pending').trim(),
      status_paid: text(draft, 'payable.status_paid').trim(),
      status_partially_refunded: text(draft, 'payable.status_partially_refunded').trim(),
      status_refunded: text(draft, 'payable.status_refunded').trim(),
    },
    currencies: list(draft, 'currencies'),
    max_amount_minor: number(draft, 'max_amount_minor'),
    success_urls: list(draft, 'success_urls'),
    cancel_urls: list(draft, 'cancel_urls'),
    roles: {
      create: list(draft, 'roles.create'), read: list(draft, 'roles.read'), read_all: list(draft, 'roles.read_all'),
      refund: list(draft, 'roles.refund'), approve_refund: list(draft, 'roles.approve_refund'), operate: list(draft, 'roles.operate'),
    },
    refund_approval_threshold_minor: optionalNumber(draft, 'refund_approval_threshold_minor'),
    scale: {
      profile: text(draft, 'scale.profile') as PaymentsWrite['scale']['profile'],
      peak_payments_per_minute: optionalNumber(draft, 'scale.peak_payments_per_minute'),
      peak_webhooks_per_minute: optionalNumber(draft, 'scale.peak_webhooks_per_minute'),
      db_max_connections: number(draft, 'scale.db_max_connections'),
      availability: text(draft, 'scale.availability') as PaymentsWrite['scale']['availability'],
      pgbouncer: checked(draft, 'scale.pgbouncer'), kubernetes: checked(draft, 'scale.kubernetes'),
      webhook_mode: (text(draft, 'scale.webhook_mode') || null) as PaymentsWrite['scale']['webhook_mode'],
      api_replicas: optionalNumber(draft, 'scale.api_replicas'),
      server_workers: optionalNumber(draft, 'scale.server_workers'),
      worker_replicas: optionalNumber(draft, 'scale.worker_replicas'),
      worker_concurrency: optionalNumber(draft, 'scale.worker_concurrency'),
      pool_size: optionalNumber(draft, 'scale.pool_size'),
      webhook_events_retention_days: number(draft, 'scale.webhook_events_retention_days'),
      jobs_retention_days: number(draft, 'scale.jobs_retention_days'),
    },
    security: {
      webhook_tolerance_seconds: number(draft, 'security.webhook_tolerance_seconds'),
      webhook_max_body_bytes: number(draft, 'security.webhook_max_body_bytes'),
      webhook_ip_allowlist_enabled: checked(draft, 'security.webhook_ip_allowlist_enabled'),
      idempotency_ttl_hours: number(draft, 'security.idempotency_ttl_hours'),
      audit_retention_days: number(draft, 'security.audit_retention_days'),
      secrets_from_files: checked(draft, 'security.secrets_from_files'),
      allow_payer_edits: checked(draft, 'security.allow_payer_edits'),
    },
  }
}

function usePaymentGroups(props: EditorProps & { model?: Model }): Group[] {
  const t = useT()
  const { draft, guided, model, change } = props
  const mode = currencyMode(draft)
  const fields = useFields({ ...props, draft: { ...draft, currencyMode: mode } }, 'payments')
  const { input, numeric, choice, toggle, values } = fields
  const translated = (options: string[], descriptions = false) => options.map(value => ({
    value, label: t('connect.payments.options.' + value),
    description: descriptions ? t('connect.payments.options.' + value + 'Help') : undefined,
  }))
  const provider = text(draft, 'provider') as PaymentsWrite['provider']
  const available = currencies[provider] ?? []
  const codes = list(draft, 'currencies')
  const entity = text(draft, 'payable.entity').trim()
  const columns = model?.entities?.find(item => item.name === entity)?.fields ?? []
  const names = (filter: (field: typeof columns[number]) => boolean) => columns.filter(filter).map(field => field.name)
  const statusesAvailable = columns.find(item => item.name === text(draft, 'payable.status_field'))?.enum_values ?? []
  const resetPayable = (names: readonly string[]) => names.forEach(name => change('payable.' + name, ''))
  const named = (name: string, options: readonly string[], validate = [validators.length(connectLimits.payableName)]) =>
    guided ? choice('payable.' + name, simple(options), {
      required: true, validate, onPick: name === 'status_field' ? () => resetPayable(statuses) : undefined,
    })
      : input('payable.' + name, [validators.required, ...validate], { maxLength: connectLimits.payableName })

  const payable = [
    guided ? choice('payable.entity', simple(model?.entities?.map(item => item.name) ?? []), {
      allowEmpty: true, onPick: () => resetPayable(['amount_field', 'currency_field', 'status_field', ...statuses]),
    })
      : input('payable.entity', [validators.length(connectLimits.payableName)], { maxLength: connectLimits.payableName }),
    ...(entity ? [
      named('amount_field', names(field => field.type === 'decimal' && field.required)),
      choice('currencyMode', translated(['fixed', 'field']), { cards: true }),
      mode === 'fixed' ? named('currency', codes.length ? codes : available, [connectCurrency])
        : named('currency_field', names(field => field.type === 'string' && field.required && field.max_length === 3)),
      named('status_field', names(field => field.type === 'enum' && field.required)),
      ...statuses.map(name => named(name, statusesAvailable, [
        validators.length(connectLimits.payableName), () => connectDistinct(statuses.map(status => text(draft, 'payable.' + status).trim())),
      ])),
    ] : []),
  ]
  return [
    { title: t('connect.payments.provider'), fields: [choice('provider', translated(['stripe', 'razorpay'], true), { cards: true })] },
    { title: t('connect.payments.payable'), description: t('connect.payments.payableHelp'), fields: payable },
    { title: t('connect.payments.checkout'), fields: [
      values('currencies', connectList(connectLimits.currencies, value => available.includes(value)), {
        choices: guided ? available.map(value => ({ value, label: t('connect.payments.currencyDecimals', { value, count: zeroDecimal.includes(value) ? 0 : 2 }) })) : undefined,
        hint: t('connect.payments.currenciesHelp'),
      }),
      numeric('max_amount_minor', 1, connectLimits.amount),
      values('success_urls', connectUrls, { hint: t('connect.payments.urlHelp') }),
      values('cancel_urls', connectUrls, { hint: t('connect.payments.urlHelp') }),
    ] },
    fields.permissions(roleActions, model?.auth?.roles?.map(role => ({ value: role.name, label: role.label || role.name })) ?? []),
    { title: t('connect.payments.refunds'), fields: [
      numeric('refund_approval_threshold_minor', 1, connectLimits.amount, true, connectRefund(number(draft, 'max_amount_minor'))),
    ] },
    { title: t('connect.payments.scale'), fields: [
      choice('scale.profile', translated(['small', 'medium', 'large'], true), { cards: true }),
      numeric('scale.peak_payments_per_minute', 1, 10_000_000, true),
      numeric('scale.peak_webhooks_per_minute', 1, 100_000_000, true),
      numeric('scale.db_max_connections', 10, 100_000),
      choice('scale.availability', translated(['single', 'ha'])),
      toggle('scale.pgbouncer'), toggle('scale.kubernetes'),
    ] },
    { title: t('connect.payments.overrides'), disclosure: t('connect.payments.overrideDisclosure'), fields: [
      choice('scale.webhook_mode', translated(['inline', 'queued']), { allowEmpty: true }),
      numeric('scale.api_replicas', 1, 1000, true), numeric('scale.server_workers', 1, 64, true),
      numeric('scale.worker_replicas', 1, 1000, true), numeric('scale.worker_concurrency', 1, 256, true),
      numeric('scale.pool_size', 1, 100, true), numeric('scale.webhook_events_retention_days', 7, 3650),
      numeric('scale.jobs_retention_days', 1, 365),
    ] },
    { title: t('connect.payments.security'), disclosure: t('connect.payments.securityDisclosure'), fields: [
      numeric('security.webhook_tolerance_seconds', 30, 600), numeric('security.webhook_max_body_bytes', 1024, 1_048_576),
      toggle('security.webhook_ip_allowlist_enabled'), numeric('security.idempotency_ttl_hours', 24, 168),
      numeric('security.audit_retention_days', 365, 36_500), toggle('security.secrets_from_files'), toggle('security.allow_payer_edits'),
    ] },
  ]
}

const measurements = ['payments_per_minute', 'api_replicas', 'worker_replicas'] as const
const sizingRows = ['webhooks_per_minute', 'webhook_mode', 'server_workers', 'api_replicas_max', 'worker_concurrency',
  'worker_replicas_max', 'total_db_connections', 'connection_budget', 'pool_size', 'max_overflow', 'worker_pool_size',
  'poll_interval_seconds', 'batch_size', 'pgbouncer_pool_size'] as const

function SizingFacts({ sizing }: { sizing: PaymentsSizing }) {
  const t = useT()
  const language = useLanguage()
  const formatter = new Intl.NumberFormat(language.language)
  return <Stack>
    <Grid gap={3}>{measurements.map(key => <Stack key={key} gap={1}>
      <strong>{formatter.format(sizing[key])}</strong><span>{t('connect.payments.sizing.' + key)}</span>
    </Stack>)}</Grid>
    <Grid gap={2}>{sizingRows.map(key => {
      const value = sizing[key]
      return <Stack key={key} gap={1}><strong>{t('connect.payments.sizing.' + key)}</strong>
        <span>{typeof value === 'number' ? formatter.format(value) : t(value === null ? 'connect.off' : 'connect.payments.options.' + value)}</span>
      </Stack>
    })}</Grid>
    <Progress label={t('connect.payments.sizing.connectionUse')} value={sizing.total_db_connections}
      max={Math.max(1, sizing.connection_budget, sizing.total_db_connections)} />
    {sizing.needs_pgbouncer && <Badge tone="warning">{t('connect.payments.sizing.pgbouncerNeeded')}</Badge>}
    {sizing.warnings.map(warning => <p key={warning}>{t('common.serverText', { text: warning })}</p>)}
    <Disclosure label={t('connect.payments.assumptions')}><Stack gap={1}>
      {sizing.assumptions.map(value => <p key={value}>{t('common.serverText', { text: value })}</p>)}
    </Stack></Disclosure>
  </Stack>
}

const providerSetup = {
  stripe: {
    env: ['STRIPE_SECRET_KEY', 'STRIPE_WEBHOOK_SECRETS'],
    events: ['checkout.session.completed', 'checkout.session.async_payment_succeeded', 'checkout.session.async_payment_failed',
      'checkout.session.expired', 'charge.refunded', 'refund.created', 'refund.updated', 'charge.refund.updated',
      'charge.dispute.created', 'charge.dispute.updated', 'charge.dispute.closed'],
  },
  razorpay: {
    env: ['RAZORPAY_KEY_ID', 'RAZORPAY_KEY_SECRET', 'RAZORPAY_WEBHOOK_SECRETS'],
    events: ['payment_link.paid', 'payment_link.expired', 'payment_link.cancelled', 'refund.created', 'refund.processed', 'refund.failed',
      'payment.dispute.created', 'payment.dispute.won', 'payment.dispute.lost', 'payment.dispute.closed',
      'payment.dispute.under_review', 'payment.dispute.action_required'],
  },
}

function PaymentsExtras({ projectId, saved }: { projectId: string; saved: PaymentsConfig }) {
  const t = useT()
  const sizing = useQuery(sizingOptions(projectId, true))
  const setup = providerSetup[saved.provider]
  return <Stack>
    <SettingsSection title={t('connect.payments.sizingTitle')}>
      {sizing.isPending && <Skeleton label={t('common.loading')} lines={5} />}
      {sizing.isError && <RetryAlert message={t('connect.payments.sizingError')} error={sizing.error} retry={() => void sizing.refetch()} />}
      {sizing.data && <Stack>
        <SizingFacts sizing={sizing.data.sizing} />
        <Disclosure label={t('connect.payments.topology')}><ol>
          <li>{t('connect.payments.sizing.api_replicas')}</li>
          <li>{t('connect.payments.sizing.worker_replicas')}</li>
          <li>{t(sizing.data.sizing.pgbouncer_pool_size ? 'connect.payments.poolDatabase' : 'connect.payments.database')}</li>
        </ol></Disclosure>
      </Stack>}
    </SettingsSection>
    <SettingsSection title={t('connect.payments.checkoutFlow')}>
      <ol><li>{t('connect.payments.flowPayer')}</li><li>{t('connect.payments.options.' + saved.provider)}</li>
        <li>{t('connect.payments.flowWebhook')}</li><li>{t('connect.payments.flowStatus')}</li>
        <li>{t(saved.refund_approval_threshold_minor ? 'connect.payments.flowApproval' : 'connect.payments.flowRefund')}</li></ol>
      {saved.payable && <Row>{statuses.map(key => <Badge key={key}>{t('common.serverText', { text: saved.payable![key] })}</Badge>)}</Row>}
    </SettingsSection>
    {saved.payable && <SettingsSection title={t('connect.payments.tables')} description={t('connect.payments.payableEntity', { name: saved.payable.entity })}>
      <CodeBlock code={'pay_payments, pay_refunds, pay_disputes, pay_webhook_events, pay_jobs, pay_audit_log, pay_idempotency_keys, pay_lock'} />
    </SettingsSection>}
    <SettingsSection title={t('connect.payments.setup')} description={t('connect.payments.setupHelp')}>
      <CodeBlock code={[...setup.env, 'APP_ENV', ...(saved.security.webhook_ip_allowlist_enabled ? ['PAYMENTS_WEBHOOK_IP_ALLOWLIST'] : [])].join('\n')}
        label={t('connect.environment')} />
      <CodeBlock code={'https://<your-api>/payments/webhooks/' + saved.provider} label={t('connect.payments.webhook')} />
      <Disclosure label={t('connect.payments.events')}><CodeBlock code={setup.events.join('\n')} /></Disclosure>
    </SettingsSection>
  </Stack>
}

function PaymentsIssues({ projectId }: { projectId: string }) {
  const sizing = useQuery(sizingOptions(projectId, true))
  return <IssueList issues={sizing.data?.issues ?? []} />
}

export default function PaymentsScreen(props: ConnectProps) {
  const read = useQuery(paymentsOptions(props.projectId))
  const write = usePaymentsWrite(props.projectId)
  return <SettingsPage {...props} kind="payments" defaults={paymentsDefaults} read={read} write={write}
    useGroups={usePaymentGroups} toWrite={toWrite}
    review={saved => saved && <PaymentsIssues projectId={props.projectId} />}
    extras={saved => saved && <PaymentsExtras projectId={props.projectId} saved={saved} />} />
}
