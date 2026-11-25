import type { Invoice as InvoiceRow, Minor, StatementLine } from '../../../../shell/money/moneyLogic'

export type InvoiceLine = {
  id: string; description: string; quantity: number; tax_rate: string | null; unit_price_minor: Minor;
  net_minor: Minor; tax_minor: Minor; gross_minor: Minor
}
export type Payment = { id: string; paid_on: string; reference: string | null; amount_minor: Minor; ledger_transaction_id: string }
export type Invoice = InvoiceRow & {
  subtotal_minor: Minor; tax_minor: Minor; counterparty_ref: string | null; notes: string | null;
  issue_transaction_id: string | null; void_transaction_id: string | null;
  created_at: string; issued_at: string | null; voided_at: string | null; lines: InvoiceLine[]; payments: Payment[]
}
export type InvoiceInput = {
  kind?: Invoice['kind']; counterparty: string; counterparty_ref: string | null; currency: string;
  issue_date: string | null; due_date: string | null; notes: string | null;
  lines: { description: string; quantity: number; unit_price_minor: number; tax_rate?: string }[]
}
export type Aging = { currencies: {
  currency: string; current_minor: Minor; current_count: number; total_minor: Minor; count: number;
  buckets: { label: string; amount_minor: Minor; count: number }[]
}[] }
export type Payout = {
  id: string; invoice_id: string; seller: string; currency: string; gross_minor: Minor; commission_bp: number;
  commission_minor: Minor; seller_minor: Minor; split_transaction_id: string; payout_transaction_id: string | null; created_at: string
}
export type PayoutTotal = Pick<Payout, 'seller' | 'currency' | 'gross_minor' | 'commission_minor' | 'seller_minor'> & { count: number }
export type Run = {
  id: string; account_id: string; currency: string; name: string | null; period_start: string | null; period_end: string | null;
  status: string; line_count: number; matched_count: number; created_at: string; closed_at: string | null; summary: Summary | null
}
export type RunInput = {
  account_id: string; name?: string; period_start?: string; period_end?: string; idempotency_key: string; lines: StatementLine[]
}
type Summary = Record<'statement_total_minor' | 'matched_lines_minor' | 'matched_entries_minor' | 'matched_diff_minor' |
  'unmatched_lines_minor' | 'unmatched_entries_minor' | 'difference_minor', Minor>
export type Line = Omit<StatementLine, 'amount_minor'> & { id: string; amount_minor: Minor }
export type EntryRef = { id: string; transaction_id: string; date: string; amount_minor: Minor; reference: string | null; description: string | null }
export type Match = { id: string; method: string; diff_minor: Minor; matched_at: string }
export type Results = {
  run: Run; summary: Summary; matched: { match: Match; line: Line; entry: EntryRef }[]; matched_total: number;
  unmatched_lines: Line[]; unmatched_entries: EntryRef[]; entries_truncated: boolean
}
