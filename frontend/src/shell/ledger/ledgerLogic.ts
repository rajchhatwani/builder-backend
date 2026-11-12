/** Pure logic of the Ledger explorer (F5-1). All money maths is integer/BigInt on minor units; no floats anywhere. */

export type Minor = bigint | number | string

export interface Account { id: string; code: string; name: string; kind: string; currency: string; exponent: number; created_at?: string }
export interface Entry { id: string; line_no: number; account_id: string; currency: string; amount_minor: Minor; direction: string }
export interface Transaction {
  id: string; idempotency_key: string; description: string | null; reference: string | null
  reverses_id: string | null; reversed_by_id: string | null; posted_at: string; posted_by: string | null; entries: Entry[]
}
export interface AccountEntry { id: string; transaction_id: string; line_no: number; currency: string; amount_minor: Minor; direction: string; posted_at: string; description: string | null; reverses_id: string | null }
export interface BalanceRow { account_id: string; code: string; name: string; currency: string; exponent: number; balance_minor: Minor; debit_total_minor: Minor; credit_total_minor: Minor }
export interface Balances { items: BalanceRow[]; totals: { currency: string; sum_minor: Minor }[] }

/** Amount fields are quoted before JSON.parse so integers beyond 2^53 keep every digit. */
const AMOUNT_KEYS = /("(?:amount_minor|balance_minor|debit_total_minor|credit_total_minor|sum_minor)"\s*:\s*)(-?\d+)/g
export const parseLedgerJson = (text: string): unknown => JSON.parse(text.replace(AMOUNT_KEYS, '$1"$2"'))

export const toBig = (v: Minor): bigint => {
  if (typeof v === 'bigint') return v
  if (typeof v === 'number') return BigInt(Math.trunc(v))
  return /^-?\d+$/.test(v) ? BigInt(v) : 0n
}

const safeExp = (e: number) => (Number.isInteger(e) && e >= 0 && e <= 18 ? e : 2)

/** Minor units to a display string: 1234/2 -> "12.34", 500/0 -> "500", -1500/3 -> "-1.500". Thousands are grouped with ",". */
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

/** A typed major-unit amount ("12.34") to minor units. Null when malformed or it has more decimals than the currency allows. */
export function parseMajor(text: string, exponent: number): bigint | null {
  const exp = safeExp(exponent)
  const m = text.trim().match(/^(\d+)(?:\.(\d*))?$/)
  if (!m) return null
  const frac = m[2] ?? ''
  if (frac.length > exp) return null
  return BigInt(m[1] + frac.padEnd(exp, '0'))
}

/** Per-currency sums of signed entry amounts. */
export function sumByCurrency(rows: { currency: string; amount_minor: Minor }[]): Map<string, bigint> {
  const out = new Map<string, bigint>()
  for (const r of rows) out.set(r.currency, (out.get(r.currency) ?? 0n) + toBig(r.amount_minor))
  return out
}

/** True when every per-currency total is exactly zero ("books balance"). */
export const booksBalance = (totals: { sum_minor: Minor }[]): boolean => totals.every((t) => toBig(t.sum_minor) === 0n)

export interface DraftLine { accountId: string; side: 'debit' | 'credit'; amount: string }

/** Draft lines to the API entries, or a message for the first problem. Amounts are signed minor units (debit positive). */
export function buildEntries(lines: DraftLine[], accounts: Account[]): { entries: { account_id: string; amount_minor: number }[]; error: null } | { entries: null; error: string } {
  if (lines.length < 2) return { entries: null, error: 'Add at least two entries.' }
  const out: { account_id: string; amount_minor: number }[] = []
  for (const [i, l] of lines.entries()) {
    const acc = accounts.find((a) => a.id === l.accountId)
    if (!acc) return { entries: null, error: `Entry ${i + 1}: choose an account.` }
    const minor = parseMajor(l.amount, acc.exponent)
    if (minor === null) return { entries: null, error: `Entry ${i + 1}: enter a positive amount with at most ${acc.exponent} decimals for ${acc.currency}.` }
    if (minor === 0n) return { entries: null, error: `Entry ${i + 1}: the amount cannot be zero.` }
    if (minor > BigInt(Number.MAX_SAFE_INTEGER)) return { entries: null, error: `Entry ${i + 1}: the amount is too large.` }
    out.push({ account_id: acc.id, amount_minor: Number(l.side === 'debit' ? minor : -minor) })
  }
  return { entries: out, error: null }
}

export const newIdempotencyKey = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

/** Human message for a ledger error body {code,message,details}. `exponents` maps currency to exponent so "off by" amounts format. */
export function ledgerErrorMessage(status: number, body: unknown, exponents: Record<string, number> = {}): string {
  const b = (typeof body === 'object' && body !== null ? body : {}) as { code?: unknown; message?: unknown; details?: unknown }
  const code = typeof b.code === 'string' ? b.code : ''
  const message = typeof b.message === 'string' ? b.message : ''
  switch (code) {
    case 'unbalanced': {
      const parts = (Array.isArray(b.details) ? b.details : []).map((d) => {
        const o = (typeof d === 'object' && d !== null ? d : {}) as Record<string, unknown>
        const cur = typeof o.currency === 'string' ? o.currency : ''
        const sum = o.sum_minor ?? o.sum
        if (!cur || (typeof sum !== 'number' && typeof sum !== 'string' && typeof sum !== 'bigint')) return typeof d === 'string' ? d : ''
        return `${cur} is off by ${formatMinor(sum, exponents[cur] ?? 2)}`
      }).filter(Boolean)
      return `The transaction does not balance${parts.length ? `: ${parts.join('; ')}` : ''}. Debits and credits must sum to zero in every currency.`
    }
    case 'already_reversed': return 'This transaction has already been reversed.'
    case 'cannot_reverse_reversal': return 'A reversal cannot itself be reversed.'
    case 'idempotency_conflict': return 'That idempotency key was already used with different contents. Generate a new key.'
    case 'unknown_account': return 'One of the accounts does not exist.'
    case 'not_found': return 'Not found.'
    default:
      if (status === 401) return 'The token was not accepted. Paste a valid bearer token.'
      if (status === 403) return 'Your role may not do this (the spec lists read and post roles for the ledger).'
      return message || `The ledger API answered ${status}.`
  }
}
