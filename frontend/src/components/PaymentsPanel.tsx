import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError } from '../api/client'
import type {
  Entity,
  Field,
  PaymentProvider,
  PaymentsAvailability,
  PaymentsConfig,
  PaymentsImpact,
  PaymentsProfile,
  PaymentsRoles,
  PaymentsSizing,
  PaymentsWrite,
  Project,
  ProjectRole,
  ValidationIssue,
  WebhookMode,
} from '../api/types'
import { Modal } from './Modal'
import { useUi } from './Ui'

interface PaymentsPanelProps {
  project: Project
  entities: Entity[]
  roles: ProjectRole[]
  authEnabled: boolean
  issues: ValidationIssue[] | null
  /** Called after anything changed so the project page can reload. */
  onChanged: () => void
}

const TWO_DECIMALS = [
  'AED', 'AUD', 'BGN', 'BRL', 'CAD', 'CHF', 'CZK', 'DKK', 'EUR', 'GBP', 'HKD', 'IDR', 'ILS', 'INR',
  'MXN', 'MYR', 'NOK', 'NZD', 'PHP', 'PLN', 'RON', 'SAR', 'SEK', 'SGD', 'THB', 'TRY', 'USD', 'ZAR',
]
const NO_DECIMALS = ['CLP', 'JPY', 'KRW', 'PYG', 'RWF', 'VND', 'XAF', 'XOF', 'XPF']
const ALL_CURRENCIES = [...TWO_DECIMALS, ...NO_DECIMALS].sort()
const RAZORPAY_CURRENCIES = ['AED', 'AUD', 'CAD', 'EUR', 'GBP', 'HKD', 'INR', 'SGD', 'USD']

const PROVIDERS: Record<PaymentProvider, { title: string; help: string }> = {
  stripe: {
    title: 'Stripe',
    help: 'Stripe Checkout: the payer pays on a page Stripe hosts. Many currencies; excellent test mode.',
  },
  razorpay: {
    title: 'Razorpay',
    help: 'Razorpay Payment Links: the payer pays on a page Razorpay hosts. Built for INR (other currencies need international payments switched on in your Razorpay account).',
  },
}

const ROLE_ROWS: { key: keyof PaymentsRoles; label: string; help: string }[] = [
  { key: 'create', label: 'Start a payment', help: 'The people who pay (customers).' },
  { key: 'read', label: 'See their own payments', help: 'Usually the same people.' },
  { key: 'read_all', label: 'See every payment', help: 'Support and finance staff (within a tenant).' },
  { key: 'refund', label: 'Refund a payment', help: 'Leave empty if nobody should refund from the API.' },
  { key: 'approve_refund', label: 'Approve large refunds', help: 'A second person. Needed only if you set a limit below.' },
  { key: 'operate', label: 'Operate the system', help: 'See queue health and failed jobs, check the audit trail.' },
]

const PROFILES: { id: PaymentsProfile; label: string; help: string }[] = [
  { id: 'small', label: 'Small', help: 'About 10 payments a minute at peak' },
  { id: 'medium', label: 'Medium', help: 'About 120 a minute' },
  { id: 'large', label: 'Large', help: 'About 1,200 a minute' },
]

interface Form {
  provider: PaymentProvider
  entity: string
  amountField: string
  currencyMode: 'fixed' | 'field'
  currency: string
  currencyField: string
  statusField: string
  statusPending: string
  statusPaid: string
  statusPartiallyRefunded: string
  statusRefunded: string
  currencies: string[]
  maxAmountMinor: number
  successUrls: string
  cancelUrls: string
  roles: PaymentsRoles
  threshold: string
  profile: PaymentsProfile
  peakPayments: string
  peakWebhooks: string
  dbMaxConnections: number
  availability: PaymentsAvailability
  pgbouncer: boolean
  kubernetes: boolean
  webhookMode: '' | WebhookMode
  apiReplicas: string
  serverWorkers: string
  workerReplicas: string
  workerConcurrency: string
  poolSize: string
  eventsRetentionDays: number
  jobsRetentionDays: number
  toleranceSeconds: number
  maxBodyBytes: number
  ipAllowlist: boolean
  idempotencyHours: number
  auditRetentionDays: number
  secretsFromFiles: boolean
  allowPayerEdits: boolean
}

const EMPTY_ROLES: PaymentsRoles = {
  create: [],
  read: [],
  read_all: [],
  refund: [],
  approve_refund: [],
  operate: [],
}

const DEFAULT_FORM: Form = {
  provider: 'stripe',
  entity: '',
  amountField: '',
  currencyMode: 'fixed',
  currency: 'USD',
  currencyField: '',
  statusField: '',
  statusPending: '',
  statusPaid: '',
  statusPartiallyRefunded: '',
  statusRefunded: '',
  currencies: ['USD'],
  maxAmountMinor: 10_000_000,
  successUrls: 'http://localhost:3000/paid',
  cancelUrls: 'http://localhost:3000/cart',
  roles: EMPTY_ROLES,
  threshold: '',
  profile: 'small',
  peakPayments: '',
  peakWebhooks: '',
  dbMaxConnections: 100,
  availability: 'single',
  pgbouncer: false,
  kubernetes: false,
  webhookMode: '',
  apiReplicas: '',
  serverWorkers: '',
  workerReplicas: '',
  workerConcurrency: '',
  poolSize: '',
  eventsRetentionDays: 90,
  jobsRetentionDays: 30,
  toleranceSeconds: 300,
  maxBodyBytes: 262144,
  ipAllowlist: false,
  idempotencyHours: 48,
  auditRetentionDays: 2555,
  secretsFromFiles: true,
  allowPayerEdits: false,
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : null
}

function formFrom(c: PaymentsConfig): Form {
  const p = c.payable
  return {
    provider: c.provider,
    entity: p?.entity ?? '',
    amountField: p?.amount_field ?? '',
    currencyMode: p?.currency_field ? 'field' : 'fixed',
    currency: p?.currency ?? c.currencies[0] ?? 'USD',
    currencyField: p?.currency_field ?? '',
    statusField: p?.status_field ?? '',
    statusPending: p?.status_pending ?? '',
    statusPaid: p?.status_paid ?? '',
    statusPartiallyRefunded: p?.status_partially_refunded ?? '',
    statusRefunded: p?.status_refunded ?? '',
    currencies: c.currencies,
    maxAmountMinor: c.max_amount_minor,
    successUrls: c.success_urls.join('\n'),
    cancelUrls: c.cancel_urls.join('\n'),
    roles: c.roles,
    threshold: c.refund_approval_threshold_minor === null ? '' : String(c.refund_approval_threshold_minor),
    profile: c.scale.profile,
    peakPayments: c.scale.peak_payments_per_minute === null ? '' : String(c.scale.peak_payments_per_minute),
    peakWebhooks: c.scale.peak_webhooks_per_minute === null ? '' : String(c.scale.peak_webhooks_per_minute),
    dbMaxConnections: c.scale.db_max_connections,
    availability: c.scale.availability,
    pgbouncer: c.scale.pgbouncer,
    kubernetes: c.scale.kubernetes,
    webhookMode: c.scale.webhook_mode ?? '',
    apiReplicas: c.scale.api_replicas === null ? '' : String(c.scale.api_replicas),
    serverWorkers: c.scale.server_workers === null ? '' : String(c.scale.server_workers),
    workerReplicas: c.scale.worker_replicas === null ? '' : String(c.scale.worker_replicas),
    workerConcurrency: c.scale.worker_concurrency === null ? '' : String(c.scale.worker_concurrency),
    poolSize: c.scale.pool_size === null ? '' : String(c.scale.pool_size),
    eventsRetentionDays: c.scale.webhook_events_retention_days,
    jobsRetentionDays: c.scale.jobs_retention_days,
    toleranceSeconds: c.security.webhook_tolerance_seconds,
    maxBodyBytes: c.security.webhook_max_body_bytes,
    ipAllowlist: c.security.webhook_ip_allowlist_enabled,
    idempotencyHours: c.security.idempotency_ttl_hours,
    auditRetentionDays: c.security.audit_retention_days,
    secretsFromFiles: c.security.secrets_from_files,
    allowPayerEdits: c.security.allow_payer_edits,
  }
}

function lines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

function toWrite(f: Form): PaymentsWrite {
  const hasPayable = f.entity !== '' && f.amountField !== '' && f.statusField !== ''
  return {
    provider: f.provider,
    payable: hasPayable
      ? {
          entity: f.entity,
          amount_field: f.amountField,
          currency: f.currencyMode === 'fixed' ? f.currency : null,
          currency_field: f.currencyMode === 'field' ? f.currencyField : null,
          status_field: f.statusField,
          status_pending: f.statusPending,
          status_paid: f.statusPaid,
          status_partially_refunded: f.statusPartiallyRefunded,
          status_refunded: f.statusRefunded,
        }
      : null,
    currencies: f.currencies,
    max_amount_minor: Number(f.maxAmountMinor),
    success_urls: lines(f.successUrls),
    cancel_urls: lines(f.cancelUrls),
    roles: f.roles,
    refund_approval_threshold_minor: numberOrNull(f.threshold),
    scale: {
      profile: f.profile,
      peak_payments_per_minute: numberOrNull(f.peakPayments),
      peak_webhooks_per_minute: numberOrNull(f.peakWebhooks),
      db_max_connections: Number(f.dbMaxConnections),
      availability: f.availability,
      pgbouncer: f.pgbouncer,
      kubernetes: f.kubernetes,
      webhook_mode: f.webhookMode === '' ? null : f.webhookMode,
      api_replicas: numberOrNull(f.apiReplicas),
      server_workers: numberOrNull(f.serverWorkers),
      worker_replicas: numberOrNull(f.workerReplicas),
      worker_concurrency: numberOrNull(f.workerConcurrency),
      pool_size: numberOrNull(f.poolSize),
      webhook_events_retention_days: Number(f.eventsRetentionDays),
      jobs_retention_days: Number(f.jobsRetentionDays),
    },
    security: {
      webhook_tolerance_seconds: Number(f.toleranceSeconds),
      webhook_max_body_bytes: Number(f.maxBodyBytes),
      webhook_ip_allowlist_enabled: f.ipAllowlist,
      idempotency_ttl_hours: Number(f.idempotencyHours),
      audit_retention_days: Number(f.auditRetentionDays),
      secrets_from_files: f.secretsFromFiles,
      allow_payer_edits: f.allowPayerEdits,
    },
  }
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

function Section({ title, children, open = true }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details open={open} className="auth-section">
      <summary>{title}</summary>
      <div className="auth-section-body">{children}</div>
    </details>
  )
}

export function PaymentsPanel({ project, entities, roles, authEnabled, issues, onChanged }: PaymentsPanelProps) {
  const { toast } = useUi()
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<PaymentsConfig | null>(null)
  const [form, setForm] = useState<Form>(DEFAULT_FORM)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [switching, setSwitching] = useState<'enable' | 'disable' | null>(null)
  const [fields, setFields] = useState<Field[]>([])
  const [sizing, setSizing] = useState<PaymentsSizing | null>(null)

  const active = config?.enabled === true

  async function load() {
    setLoading(true)
    try {
      const loaded = await api.getPayments(project.id)
      setConfig(loaded)
      setForm(formFrom(loaded))
      api
        .paymentsSizing(project.id)
        .then((result) => setSizing(result.sizing))
        .catch(() => setSizing(null))
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setConfig(null)
        setForm(DEFAULT_FORM)
        setSizing(null)
      } else {
        setMessage({ ok: false, text: errorText(err, 'Could not load the payments settings.') })
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [project.id])

  // The fields of the chosen entity feed the pickers below.
  const entity = entities.find((e) => e.name === form.entity)
  useEffect(() => {
    let cancelled = false
    if (!entity) {
      setFields([])
      return
    }
    api.listFields(entity.id, 200, 0).then((page) => {
      if (!cancelled) setFields(page.items)
    })
    return () => {
      cancelled = true
    }
  }, [entity?.id])

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function setRole(key: keyof PaymentsRoles, name: string, on: boolean) {
    const current = form.roles[key]
    set('roles', { ...form.roles, [key]: on ? [...current, name] : current.filter((r) => r !== name) })
  }

  function toggleCurrency(code: string, on: boolean) {
    set('currencies', on ? [...form.currencies, code].sort() : form.currencies.filter((c) => c !== code))
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const saved = await api.putPayments(project.id, toWrite(form))
      setConfig(saved)
      setForm(formFrom(saved))
      toast('Payments settings saved.')
      api
        .paymentsSizing(project.id)
        .then((result) => setSizing(result.sizing))
        .catch(() => setSizing(null))
      onChanged()
    } catch (err) {
      setMessage({ ok: false, text: errorText(err, 'Could not save the payments settings.') })
    } finally {
      setSaving(false)
    }
  }

  const paymentsIssues = useMemo(
    () => (issues ?? []).filter((i) => i.path === 'payments' || i.path.startsWith('payments.')),
    [issues],
  )
  const decimalFields = fields.filter((f) => f.type === 'decimal')
  const stringFields = fields.filter((f) => f.type === 'string')
  const enumFields = fields.filter((f) => f.type === 'enum')
  const statusValues = enumFields.find((f) => f.name === form.statusField)?.enum_values ?? []
  const allowedCurrencies = form.provider === 'razorpay' ? RAZORPAY_CURRENCIES : ALL_CURRENCIES
  const roleNames = roles.map((r) => r.name)

  if (loading) {
    return (
      <div className="card">
        <p className="empty-state">Loading…</p>
      </div>
    )
  }

  return (
    <>
      <div className="card status-card" data-active={active ? 'true' : undefined}>
        <div className="status-card-text">
          <strong>{active ? 'Payments are on for this project' : 'Payments are off for this project'}</strong>
          <p className="muted">
            {active
              ? 'The next download includes the payment module, a worker, and deployment files sized for your load.'
              : config
                ? 'Your payments settings are saved: turn payments on when you are ready.'
                : 'Fill in the settings below, then turn payments on.'}
          </p>
        </div>
        {active ? (
          <button className="outline" data-variant="danger" onClick={() => setSwitching('disable')}>
            Turn off…
          </button>
        ) : (
          <button
            disabled={!config || !authEnabled}
            title={!config ? 'Save the settings first' : !authEnabled ? 'Turn on authentication first' : undefined}
            onClick={() => setSwitching('enable')}
          >
            Turn on…
          </button>
        )}
      </div>

      {!config && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <h3>What you get</h3>
          <ul className="benefit-list">
            <li>
              <strong>Card details never touch your server.</strong> The payer pays on the provider's own page, which keeps
              you out of the heaviest card-security rules.
            </li>
            <li>
              <strong>Safe by construction.</strong> The amount is read from your own data on the server, every request can
              be repeated without charging twice, webhooks are verified by signature, and every change is written to a
              tamper-evident audit log.
            </li>
            <li>
              <strong>Scales with you.</strong> Tell us how many payments you expect and the download comes with a worker
              process, server counts, database connection limits and deployment files (Docker, and Kubernetes if you ask) worked
              out for that load, plus a guide for running workers on other servers.
            </li>
            <li>
              <strong>No secrets here.</strong> Your provider keys are environment variables of the generated project; they are
              never stored in this dashboard or in the zip.
            </li>
          </ul>
        </div>
      )}

      {!authEnabled && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <div role="alert" data-variant="danger">
            Payments need people to sign in. Turn on authentication first (Authentication or Keycloak).
          </div>
        </div>
      )}

      {paymentsIssues.length > 0 && active && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-3)' }}>
            {paymentsIssues.length} {paymentsIssues.length === 1 ? 'thing needs' : 'things need'} fixing before you can
            generate.
          </div>
          <ul className="issue-list">
            {paymentsIssues.map((issue, i) => (
              <li key={i}>
                <span>
                  {issue.message}
                  <small className="muted"> · {issue.path.replace('payments.', '')}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="card" onSubmit={handleSave}>
        {message && (
          <div role="alert" data-variant={message.ok ? 'success' : 'danger'} style={{ marginBlockEnd: 'var(--space-4)' }}>
            {message.text}
          </div>
        )}

        <Section title="Payment provider">
          <div className="choice-grid">
            {(Object.keys(PROVIDERS) as PaymentProvider[]).map((id) => (
              <label key={id} className="choice" data-selected={form.provider === id ? 'true' : undefined}>
                <input type="radio" name="provider" checked={form.provider === id} onChange={() => set('provider', id)} />
                <strong>{PROVIDERS[id].title}</strong>
                <span className="muted">{PROVIDERS[id].help}</span>
              </label>
            ))}
          </div>
        </Section>

        <Section title="What is paid for">
          <p className="muted">
            Pick the thing a payment is for (an order, an invoice). Its amount is read from your own data when the payer
            starts a payment: the payer never sends an amount.
          </p>
          <div className="field-grid">
            <label>
              Entity
              <select
                value={form.entity}
                onChange={(e) =>
                  setForm((f) => ({ ...f, entity: e.target.value, amountField: '', currencyField: '', statusField: '' }))
                }
              >
                <option value="">Choose…</option>
                {entities.map((e) => (
                  <option key={e.id} value={e.name}>
                    {e.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Amount field (decimal, in major units such as 19.99)
              <select value={form.amountField} onChange={(e) => set('amountField', e.target.value)} disabled={!entity}>
                <option value="">Choose…</option>
                {decimalFields.map((f) => (
                  <option key={f.id} value={f.name}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Currency
              <select value={form.currencyMode} onChange={(e) => set('currencyMode', e.target.value as 'fixed' | 'field')}>
                <option value="fixed">The same for every item</option>
                <option value="field">Stored on each item</option>
              </select>
            </label>
            {form.currencyMode === 'fixed' ? (
              <label>
                Currency code
                <select value={form.currency} onChange={(e) => set('currency', e.target.value)}>
                  {allowedCurrencies.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label>
                Currency field (3-letter text, required)
                <select value={form.currencyField} onChange={(e) => set('currencyField', e.target.value)} disabled={!entity}>
                  <option value="">Choose…</option>
                  {stringFields.map((f) => (
                    <option key={f.id} value={f.name}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Status field (a list of choices)
              <select
                value={form.statusField}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    statusField: e.target.value,
                    statusPending: '',
                    statusPaid: '',
                    statusPartiallyRefunded: '',
                    statusRefunded: '',
                  }))
                }
                disabled={!entity}
              >
                <option value="">Choose…</option>
                {enumFields.map((f) => (
                  <option key={f.id} value={f.name}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {form.statusField !== '' && (
            <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
              {(
                [
                  ['statusPending', 'Waiting for payment'],
                  ['statusPaid', 'Paid'],
                  ['statusPartiallyRefunded', 'Partly refunded'],
                  ['statusRefunded', 'Fully refunded'],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <select value={form[key]} onChange={(e) => set(key, e.target.value)}>
                    <option value="">Choose…</option>
                    {statusValues.map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}
          <p className="muted small-text">
            The status field moves between these values by itself as payments succeed and are refunded. Give the amount field a
            minimum above zero{form.provider === 'razorpay' ? ' (at least 1: Razorpay refuses less)' : ''}.
          </p>
        </Section>

        <Section title="Money and return addresses">
          <p className="muted">Currencies you accept (anything else is refused):</p>
          <div className="check-grid" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2) var(--space-4)' }}>
            {allowedCurrencies.map((c) => (
              <label key={c} style={{ display: 'flex', gap: 'var(--space-1)', alignItems: 'center' }}>
                <input type="checkbox" checked={form.currencies.includes(c)} onChange={(e) => toggleCurrency(c, e.target.checked)} />
                {c}
              </label>
            ))}
          </div>
          <p className="muted small-text">
            Currencies with special rules at the providers (for example KWD, HUF) are not offered on purpose.
          </p>
          <label style={{ marginBlockStart: 'var(--space-4)' }}>
            Largest single payment, in the smallest unit (cents, paise)
            <input
              type="number"
              min={1}
              max={99999999}
              value={form.maxAmountMinor}
              onChange={(e) => set('maxAmountMinor', Number(e.target.value))}
            />
          </label>
          <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
            <label>
              After paying, send the payer to (one exact address per line; the first is the default)
              <textarea rows={3} value={form.successUrls} onChange={(e) => set('successUrls', e.target.value)} />
            </label>
            <label>
              If they give up, send them to
              <textarea rows={3} value={form.cancelUrls} onChange={(e) => set('cancelUrls', e.target.value)} />
            </label>
          </div>
          <p className="muted small-text">
            Only these exact addresses are accepted, so nobody can use your checkout to redirect people elsewhere. Use https,
            except localhost while you develop.
          </p>
        </Section>

        <Section title="Who can do what">
          <p className="muted">
            Nothing is allowed to anyone unless you tick it here. The people who pay should <strong>not</strong> be able to
            create or edit the item they pay for, or they could set their own price: set that under Roles &amp; access.
          </p>
          <div className="table">
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  {roleNames.map((r) => (
                    <th key={r}>{r}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROLE_ROWS.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <strong>{row.label}</strong>
                      <br />
                      <small className="muted">{row.help}</small>
                    </td>
                    {roleNames.map((r) => (
                      <td key={r}>
                        <input
                          type="checkbox"
                          aria-label={`${row.label}: ${r}`}
                          checked={form.roles[row.key].includes(r)}
                          onChange={(e) => setRole(row.key, r, e.target.checked)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {roleNames.length === 0 && <p className="muted">Create roles first (Roles &amp; access).</p>}
          <label style={{ marginBlockStart: 'var(--space-4)' }}>
            Refunds above this amount (smallest unit) need a second person's approval (optional)
            <input
              type="number"
              min={1}
              value={form.threshold}
              placeholder="No limit"
              onChange={(e) => set('threshold', e.target.value)}
            />
          </label>
        </Section>

        <Section title="How much traffic to plan for">
          <p className="muted">
            Tell us the busiest minute you expect. The download then comes with the number of API servers, workers and database
            connections worked out for it, as ready-to-use Docker (and Kubernetes) files plus a deployment guide.
          </p>
          <div className="choice-grid">
            {PROFILES.map((p) => (
              <label key={p.id} className="choice" data-selected={form.profile === p.id ? 'true' : undefined}>
                <input type="radio" name="profile" checked={form.profile === p.id} onChange={() => set('profile', p.id)} />
                <strong>{p.label}</strong>
                <span className="muted">{p.help}</span>
              </label>
            ))}
          </div>
          <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
            <label>
              Payments in the busiest minute (overrides the choice above)
              <input type="number" min={1} value={form.peakPayments} placeholder="From the choice above" onChange={(e) => set('peakPayments', e.target.value)} />
            </label>
            <label>
              Provider events in the busiest minute
              <input type="number" min={1} value={form.peakWebhooks} placeholder="About 5 per payment" onChange={(e) => set('peakWebhooks', e.target.value)} />
            </label>
            <label>
              Your database's connection limit (max_connections)
              <input type="number" min={10} value={form.dbMaxConnections} onChange={(e) => set('dbMaxConnections', Number(e.target.value))} />
            </label>
            <label>
              Availability
              <select value={form.availability} onChange={(e) => set('availability', e.target.value as PaymentsAvailability)}>
                <option value="single">One of everything is fine</option>
                <option value="ha">No single point of failure (at least two of each)</option>
              </select>
            </label>
          </div>
          <div style={{ display: 'grid', gap: 'var(--space-2)', marginBlockStart: 'var(--space-4)' }}>
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.pgbouncer} onChange={(e) => set('pgbouncer', e.target.checked)} />
              Put PgBouncer in front of the database (needed when many servers share a small database)
            </label>
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.kubernetes} onChange={(e) => set('kubernetes', e.target.checked)} />
              Also generate Kubernetes files
            </label>
          </div>

          <SizingPreview sizing={sizing} saved={config !== null} />

          <details style={{ marginBlockStart: 'var(--space-4)' }}>
            <summary>Advanced: set the numbers yourself</summary>
            <p className="muted small-text">Anything you fill in here replaces the calculated value. Leave a box empty to use the calculation.</p>
            <div className="field-grid">
              <label>
                Webhook handling
                <select value={form.webhookMode} onChange={(e) => set('webhookMode', e.target.value as '' | WebhookMode)}>
                  <option value="">Choose from the load</option>
                  <option value="inline">Inline: processed inside the request</option>
                  <option value="queued">Queued: stored, then handled by workers</option>
                </select>
              </label>
              <label>
                API servers
                <input type="number" min={1} value={form.apiReplicas} onChange={(e) => set('apiReplicas', e.target.value)} />
              </label>
              <label>
                Server processes per API server
                <input type="number" min={1} max={64} value={form.serverWorkers} onChange={(e) => set('serverWorkers', e.target.value)} />
              </label>
              <label>
                Payment workers
                <input type="number" min={1} value={form.workerReplicas} onChange={(e) => set('workerReplicas', e.target.value)} />
              </label>
              <label>
                Jobs per worker at once
                <input type="number" min={1} max={256} value={form.workerConcurrency} onChange={(e) => set('workerConcurrency', e.target.value)} />
              </label>
              <label>
                Database connections per process
                <input type="number" min={1} max={100} value={form.poolSize} onChange={(e) => set('poolSize', e.target.value)} />
              </label>
              <label>
                Keep provider events for (days)
                <input type="number" min={7} max={3650} value={form.eventsRetentionDays} onChange={(e) => set('eventsRetentionDays', Number(e.target.value))} />
              </label>
              <label>
                Keep finished jobs for (days)
                <input type="number" min={1} max={365} value={form.jobsRetentionDays} onChange={(e) => set('jobsRetentionDays', Number(e.target.value))} />
              </label>
            </div>
          </details>
        </Section>

        <Section title="Security" open={false}>
          <p className="muted">
            Safe defaults are already chosen. Each setting has a floor or ceiling; unsafe values are refused, never quietly
            adjusted.
          </p>
          <div className="field-grid">
            <label>
              Reject webhooks older or newer than (seconds, 30 to 600)
              <input type="number" min={30} max={600} value={form.toleranceSeconds} onChange={(e) => set('toleranceSeconds', Number(e.target.value))} />
            </label>
            <label>
              Largest webhook accepted (bytes, 1,024 to 1,048,576)
              <input type="number" min={1024} max={1048576} value={form.maxBodyBytes} onChange={(e) => set('maxBodyBytes', Number(e.target.value))} />
            </label>
            <label>
              Remember a repeated-request key for (hours, 24 to 168)
              <input type="number" min={24} max={168} value={form.idempotencyHours} onChange={(e) => set('idempotencyHours', Number(e.target.value))} />
            </label>
            <label>
              Keep the audit log at least (days, 365 or more)
              <input type="number" min={365} max={36500} value={form.auditRetentionDays} onChange={(e) => set('auditRetentionDays', Number(e.target.value))} />
            </label>
          </div>
          <div style={{ display: 'grid', gap: 'var(--space-2)', marginBlockStart: 'var(--space-4)' }}>
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.ipAllowlist} onChange={(e) => set('ipAllowlist', e.target.checked)} />
              Only accept webhooks from the provider's addresses (you give the list when you deploy)
            </label>
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.secretsFromFiles} onChange={(e) => set('secretsFromFiles', e.target.checked)} />
              Allow secrets to come from files (Docker and Kubernetes secrets)
            </label>
            <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <input type="checkbox" checked={form.allowPayerEdits} onChange={(e) => set('allowPayerEdits', e.target.checked)} />
              <span>
                <strong>Let payers create or edit what they pay for</strong>
              </span>
            </label>
          </div>
          {form.allowPayerEdits && (
            <div role="alert" data-variant="danger" style={{ marginBlockStart: 'var(--space-3)' }}>
              With this on, anyone who can pay can also change the amount before paying. Only do it if your own code checks
              the amount some other way.
            </div>
          )}
        </Section>

        <footer className="form-actions" style={{ marginBlockStart: 'var(--space-4)' }}>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save payments settings'}
          </button>
        </footer>
      </form>

      <SwitchDialog
        projectId={project.id}
        action={switching}
        onClose={() => setSwitching(null)}
        onDone={() => {
          setSwitching(null)
          load()
          onChanged()
        }}
      />
    </>
  )
}

function SizingPreview({ sizing, saved }: { sizing: PaymentsSizing | null; saved: boolean }) {
  if (!saved || sizing === null) {
    return (
      <div className="card" style={{ marginBlockStart: 'var(--space-4)' }}>
        <p className="muted">Save the settings to see the servers, workers and database connections this load needs.</p>
      </div>
    )
  }
  const rows: [string, string][] = [
    ['Planned load', `${sizing.payments_per_minute} payments and ${sizing.webhooks_per_minute} provider events per minute`],
    ['Webhook handling', sizing.webhook_mode === 'inline' ? 'Inline (inside the request)' : 'Queued (workers handle them)'],
    ['API servers', `${sizing.api_replicas} × ${sizing.server_workers} server process(es), up to ${sizing.api_replicas_max} when busy`],
    ['Payment workers', `${sizing.worker_replicas} × ${sizing.worker_concurrency} jobs at once, up to ${sizing.worker_replicas_max} when busy`],
    [
      'Database connections',
      `${sizing.total_db_connections} needed, ${sizing.connection_budget} available${
        sizing.pgbouncer_pool_size ? ` (PgBouncer keeps ${sizing.pgbouncer_pool_size} open)` : ''
      }`,
    ],
  ]
  return (
    <div className="card" style={{ marginBlockStart: 'var(--space-4)' }}>
      <h4>What this means for your servers</h4>
      <div className="table">
        <table>
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sizing.needs_pgbouncer && (
        <div role="alert" data-variant="danger" style={{ marginBlockStart: 'var(--space-3)' }}>
          This does not fit your database's connection limit. Turn on PgBouncer, raise the limit, or lower the load.
        </div>
      )}
      {sizing.warnings.length > 0 && (
        <ul className="impact-list">
          {sizing.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <p className="muted small-text">
        <strong>These are estimates, not measurements.</strong> {sizing.assumptions[sizing.assumptions.length - 1]} The download
        explains how to run workers on other servers.
      </p>
    </div>
  )
}

function SwitchDialog({
  projectId,
  action,
  onClose,
  onDone,
}: {
  projectId: string
  action: 'enable' | 'disable' | null
  onClose: () => void
  onDone: () => void
}) {
  const { toast } = useUi()
  const [impact, setImpact] = useState<PaymentsImpact | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setImpact(null)
    setError(null)
    if (action === null) return
    api
      .paymentsImpact(projectId, action)
      .then(setImpact)
      .catch((err) => setError(errorText(err, 'Could not check what this changes.')))
  }, [action, projectId])

  async function confirm(event: FormEvent) {
    event.preventDefault()
    if (action === null) return
    setBusy(true)
    setError(null)
    try {
      await api.switchPayments(projectId, action)
      toast(action === 'enable' ? 'Payments are on.' : 'Payments are off. Your settings are kept.')
      onDone()
    } catch (err) {
      setError(errorText(err, 'Could not switch.'))
    } finally {
      setBusy(false)
    }
  }

  const turningOn = action === 'enable'
  return (
    <Modal open={action !== null} onClose={onClose}>
      <form onSubmit={confirm}>
        <header>
          <h3>{turningOn ? 'Turn on payments?' : 'Turn off payments?'}</h3>
          <p>
            {turningOn
              ? 'The next download will include the payment module, a worker and deployment files.'
              : 'The next download will not include payments.'}
          </p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              {error}
            </div>
          )}
          {!impact && !error && <p className="muted">Checking what this changes…</p>}
          {impact && impact.blockers.length > 0 && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              <div>
                <strong>Not possible yet</strong>
                <ul className="impact-list">
                  {impact.blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {impact && impact.warnings.length > 0 && (
            <>
              <strong>Before you continue</strong>
              <ul className="impact-list">
                {impact.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </>
          )}
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" data-variant={turningOn ? undefined : 'danger'} disabled={busy || !impact || !impact.can_proceed}>
            {busy ? 'Working…' : turningOn ? 'Turn on payments' : 'Turn off payments'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
