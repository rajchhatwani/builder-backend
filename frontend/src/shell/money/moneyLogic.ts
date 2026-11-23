/** Pure logic shared by the money dashboards (invoices, payouts, reconciliation). Money is integer minor units / BigInt only. */

export type Minor = bigint | number | string

/** Every `*_minor` integer is quoted before JSON.parse so values beyond 2^53 keep all digits. */
const MINOR_KEYS = /("[A-Za-z_]*_minor"\s*:\s*)(-?\d+)/g
export const parseMoneyJson = (text: string): unknown => JSON.parse(text.replace(MINOR_KEYS, '$1"$2"'))

export const toBig = (v: Minor | null | undefined): bigint => {
  if (v === null || v === undefined) return 0n
  if (typeof v === 'bigint') return v
  if (typeof v === 'number') return Number.isFinite(v) ? BigInt(Math.trunc(v)) : 0n
  return /^-?\d+$/.test(v) ? BigInt(v) : 0n
}

const safeExp = (e: number) => (Number.isInteger(e) && e >= 0 && e <= 18 ? e : 2)

/** Fallback exponent when the API does not state one. */
export const defaultExponent = (currency: string): number =>
  ['CLP', 'ISK', 'JPY', 'KRW', 'PYG', 'RWF', 'UGX', 'VND', 'XAF', 'XOF', 'XPF'].includes(currency) ? 0 : ['BHD', 'KWD', 'OMR', 'JOD', 'TND'].includes(currency) ? 3 : 2

export function formatMinor(minor: Minor, exponent: number): string {
  const exp = safeExp(exponent)
  const n = toBig(minor)
  const neg = n < 0n
  const abs = neg ? -n : n
  const base = 10n ** BigInt(exp)
  const whole = (abs / base).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const frac = exp === 0 ? '' : `.${(abs % base).toString().padStart(exp, '0')}`
  return `${neg ? '-' : ''}${whole}${frac}`
}

/** Typed major-unit amount to minor units; null when malformed or too many decimals. `signed` allows a leading "-". */
export function parseMajor(text: string, exponent: number, signed = false): bigint | null {
  const exp = safeExp(exponent)
  const m = text.trim().match(/^(-?)(\d+)(?:\.(\d*))?$/)
  if (!m || (m[1] && !signed)) return null
  const frac = m[3] ?? ''
  if (frac.length > exp) return null
  const v = BigInt(m[2] + frac.padEnd(exp, '0'))
  return m[1] ? -v : v
}

/** Per-currency sums, in first-seen order. */
export function sumByCurrency<T>(rows: T[], cur: (r: T) => string, amt: (r: T) => Minor): Map<string, bigint> {
  const out = new Map<string, bigint>()
  for (const r of rows) out.set(cur(r), (out.get(cur(r)) ?? 0n) + toBig(amt(r)))
  return out
}

export const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER)

export const newIdempotencyKey = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

export interface Invoice {
  id: string; kind: 'receivable' | 'payable'; number: string | null; status: string; counterparty: string; currency: string; exponent: number
  issue_date: string | null; due_date: string | null; total_minor: Minor; paid_minor: Minor; outstanding_minor: Minor
}

/** Per-currency totals of invoice lists: total / paid / outstanding (void invoices excluded from outstanding). */
export function invoiceTotals(rows: Invoice[]): { currency: string; exponent: number; total: bigint; paid: bigint; outstanding: bigint }[] {
  const m = new Map<string, { currency: string; exponent: number; total: bigint; paid: bigint; outstanding: bigint }>()
  for (const r of rows) {
    const t = m.get(r.currency) ?? { currency: r.currency, exponent: r.exponent, total: 0n, paid: 0n, outstanding: 0n }
    t.total += toBig(r.total_minor); t.paid += toBig(r.paid_minor)
    if (r.status !== 'void') t.outstanding += toBig(r.outstanding_minor)
    m.set(r.currency, t)
  }
  return [...m.values()]
}

export interface DraftInvLine { description: string; quantity: string; unitPrice: string; taxRate: string }

/** Draft invoice lines to API lines (unit price in major units of `exponent`). */
export function buildInvoiceLines(lines: DraftInvLine[], exponent: number): { lines: { description: string; quantity: number; unit_price_minor: number; tax_rate?: string }[]; error: null } | { lines: null; error: string } {
  if (lines.length < 1) return { lines: null, error: 'Add at least one line.' }
  const out: { description: string; quantity: number; unit_price_minor: number; tax_rate?: string }[] = []
  for (const [i, l] of lines.entries()) {
    const n = i + 1
    if (!l.description.trim()) return { lines: null, error: `Line ${n}: enter a description.` }
    if (!/^\d+$/.test(l.quantity.trim()) || BigInt(l.quantity.trim()) < 1n || BigInt(l.quantity.trim()) > 1_000_000_000n) return { lines: null, error: `Line ${n}: quantity must be a whole number from 1 to 1,000,000,000.` }
    const p = parseMajor(l.unitPrice, exponent)
    if (p === null) return { lines: null, error: `Line ${n}: enter a unit price with at most ${exponent} decimals.` }
    if (p > MAX_SAFE) return { lines: null, error: `Line ${n}: the unit price is too large.` }
    const line: { description: string; quantity: number; unit_price_minor: number; tax_rate?: string } = { description: l.description.trim(), quantity: Number(l.quantity.trim()), unit_price_minor: Number(p) }
    if (l.taxRate.trim()) line.tax_rate = l.taxRate.trim()
    out.push(line)
  }
  return { lines: out, error: null }
}

/** Seller label of a payout: letters, digits and . _ : @ - ; no spaces; 1-64 chars; must start alphanumeric. */
export const validSeller = (s: string): boolean => /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,63}$/.test(s)

export interface StatementLine { external_id: string; date: string; amount_minor: number; currency: string; reference?: string }

/** Parse pasted CSV (external_id,date,amount,currency[,reference]; a header row starting with "external_id" is skipped).
 *  Amounts are signed major units (positive = debit side) converted with `exponent`. */
export function parseStatementCsv(text: string, exponent: number, currency: string): { lines: StatementLine[]; error: null } | { lines: null; error: string } {
  const rows = text.split(/\r?\n/).map((r) => r.trim()).filter(Boolean)
  if (rows.length && /^external_id\b/i.test(rows[0])) rows.shift()
  if (rows.length === 0) return { lines: null, error: 'Paste at least one statement line.' }
  const out: StatementLine[] = []
  const seen = new Set<string>()
  for (const [i, row] of rows.entries()) {
    const n = i + 1
    const c = row.split(',').map((x) => x.trim())
    if (c.length < 3) return { lines: null, error: `Row ${n}: expected external_id,date,amount[,currency[,reference]].` }
    const [id, date, amt, cur, ...ref] = c
    if (!id || id.length > 128) return { lines: null, error: `Row ${n}: external_id must be 1-128 characters.` }
    if (seen.has(id)) return { lines: null, error: `Row ${n}: external_id ${id} appears twice.` }
    seen.add(id)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(date))) return { lines: null, error: `Row ${n}: date must be YYYY-MM-DD.` }
    const m = parseMajor(amt, exponent, true)
    if (m === null) return { lines: null, error: `Row ${n}: amount must be a number with at most ${exponent} decimals.` }
    if (m === 0n) return { lines: null, error: `Row ${n}: the amount cannot be zero.` }
    if (m > MAX_SAFE || m < -MAX_SAFE) return { lines: null, error: `Row ${n}: the amount is too large.` }
    const lc = (cur || currency).toUpperCase()
    if (!/^[A-Z]{3}$/.test(lc)) return { lines: null, error: `Row ${n}: currency must be 3 letters.` }
    const line: StatementLine = { external_id: id, date, amount_minor: Number(m), currency: lc }
    const r = ref.join(',').trim()
    if (r) line.reference = r.slice(0, 128)
    out.push(line)
  }
  return { lines: out, error: null }
}

/** Human message for an API error body {code,message}. `what` names the API ("invoicing", "payouts", "reconciliation"). */
export function moneyErrorMessage(status: number, body: unknown, what = 'invoicing'): string {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; message?: unknown }
  const code = typeof b.code === 'string' ? b.code : ''
  const message = typeof b.message === 'string' ? b.message : ''
  switch (code) {
    case 'idempotency_conflict': return 'That idempotency key was already used with different contents. Generate a new key.'
    case 'unknown_tax_rate': return message || 'A line uses a tax rate this project does not define.'
    case 'unsupported_currency': return message || 'That currency is not enabled for this project.'
    case 'has_payments': return 'An invoice with payments cannot be voided.'
    case 'already_paid_out': return 'This invoice has already been paid out.'
    case 'invoice_not_paid': return 'An invoice can be paid out only once it is fully paid.'
    case 'run_closed': return 'This reconciliation run is closed; it cannot change.'
    case 'line_already_matched': return 'That statement line is already matched.'
    case 'entry_already_matched': return 'That ledger entry is already matched.'
    case 'unknown_account': return 'The ledger account does not exist.'
    default:
      if (status === 404 && !code) return `This project has no ${what} API (404). Enable it in the spec to use this page.`
      if (status === 401) return 'Your session was not accepted. Sign in again.'
      if (status === 403) return `Your role may not do this (the spec lists read and write roles for ${what}).`
      return message || `The ${what} API answered ${status}.`
  }
}
