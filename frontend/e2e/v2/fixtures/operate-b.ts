import { time } from './connect-a'

export const fixedTime = '2026-01-05T08:00:00.000Z'
export const ownerPacks = {
  packs: {
    booking: {
      read_roles: ['admin'], book_roles: ['admin'], manage_roles: ['admin'], own_only: false,
      hold_ttl_seconds: 600, max_horizon_days: 365, cancellation: { free_until_hours: 24, fee_minor: 2500, currency: 'USD' },
      kinds: [{ name: 'interview', mode: 'slot', timezone: 'UTC', slot_minutes: 30, schedule: { mon: [{ start: '09:00', end: '12:00' }] } }],
    },
  }, version: 3, updated_at: time,
}
const account = { id: 'cash', code: '1000', name: 'Cash on hand', kind: 'asset', currency: 'USD', exponent: 2, created_at: time }
const income = { ...account, id: 'income', code: '4000', name: 'Service revenue', kind: 'income' }
const transaction = { id: 'txn', idempotency_key: 'txn-key', description: 'Opening balance', reference: 'OB-1',
  reverses_id: null, reversed_by_id: null, posted_at: time, posted_by: 'admin', entries: [
    { id: 'debit', line_no: 1, account_id: account.id, currency: 'USD', amount_minor: 12500, direction: 'debit' },
    { id: 'credit', line_no: 2, account_id: income.id, currency: 'USD', amount_minor: -12500, direction: 'credit' },
  ] }
const invoice = {
  id: 'invoice-1', kind: 'receivable', number: 'INV-1042', status: 'paid', counterparty: 'Northwind Studio',
  currency: 'USD', exponent: 2, due_date: '2026-01-31', issue_date: '2026-01-01', subtotal_minor: 10000,
  tax_minor: 2500, total_minor: 12500, paid_minor: 12500, outstanding_minor: 0, created_at: time,
  issued_at: time, voided_at: null, counterparty_ref: 'N-001', notes: null, issue_transaction_id: 'txn', void_transaction_id: null,
  lines: [{ id: 'invoice-line', description: 'Design session', quantity: 1, unit_price_minor: 10000, tax_rate: null, net_minor: 10000, tax_minor: 2500, gross_minor: 12500 }],
  payments: [{ id: 'payment', paid_on: '2026-01-05', amount_minor: 12500, reference: 'Bank transfer', ledger_transaction_id: 'txn' }],
}
const payout = { id: 'payout-1', invoice_id: 'invoice-2', seller: 'northwind.vendor', currency: 'USD', gross_minor: 5000,
  seller_minor: 4500, commission_minor: 500, commission_bp: 1000, split_transaction_id: 'txn', payout_transaction_id: 'txn', created_at: time }
const run = { id: 'run-1', account_id: account.id, name: 'January statement', currency: 'USD', period_start: '2026-01-01',
  period_end: '2026-01-31', status: 'open', line_count: 1, matched_count: 0, created_at: time, closed_at: null, summary: null }
const position = { subject_id: 'courier-17', subject_kind: 'courier', lat_micro: 51507000, lng_micro: -127500,
  lat: '51.507', lng: '-0.1275', seq: 25, recorded_at: '2026-01-05T07:59:45Z', updated_at: fixedTime }
const resource = { id: 'room-1', kind: 'interview', mode: 'slot', name: 'Interview room', timezone: 'UTC', active: true,
  slot_minutes: 30, capacity: 1, min_minutes: null, max_minutes: null, schedule: ownerPacks.packs.booking.kinds[0].schedule, created_at: time }
const slots = [
  { starts_at: '2026-01-05T09:00:00Z', ends_at: '2026-01-05T09:30:00Z', free: true },
  { starts_at: '2026-01-05T09:30:00Z', ends_at: '2026-01-05T10:00:00Z', free: false },
  { starts_at: '2026-01-06T09:00:00Z', ends_at: '2026-01-06T09:30:00Z', free: true },
]
const booking = { ...slots[1], id: 'booking-1', resource_id: resource.id, resource_name: resource.name, quantity: 1, status: 'confirmed',
  customer_ref: 'NW-1042', customer_id: 'admin', notes: 'Interview', hold_expires_at: null, created_at: fixedTime }

export const runtimeMain = {
  ledger: '/ledger/accounts', invoices: '/invoices', payouts: '/payouts', reconciliation: '/reconciliation/runs',
  map: '/location/positions', bookings: '/booking/resources', bookingadmin: '/booking/resources',
}
export const titles = {
  ledger: ['Ledger', 'Cash on hand', 'No accounts yet.'],
  invoices: ['Invoices', 'Northwind Studio', 'No invoices yet.'],
  payouts: ['Payouts', 'northwind.vendor', 'No payouts yet.'],
  reconciliation: ['Reconciliation', 'January statement', 'No reconciliation runs yet.'],
  map: ['Map', 'courier-17', 'No positions in this area.'],
  bookings: ['Bookings', 'Interview room', 'No resources yet.'],
  bookingadmin: ['Booking admin', 'Interview room', 'No resources yet.'],
} as const
export type Screen = keyof typeof titles
export const normalTables = {
  ledger: 'Accounts', invoices: 'Invoices', payouts: 'Payouts', reconciliation: 'Runs', map: 'Positions',
  bookings: 'Booking ledger', bookingadmin: 'Resources',
} satisfies Record<Screen, string>
export const bookingReference = booking.customer_ref
export const pageData = (...items: unknown[]) => ({ items, total: items.length, limit: 200, offset: 0 })
export function runtimeData(path: string, empty = false): unknown {
  const page = (...items: unknown[]) => pageData(...(empty ? [] : items))
  switch (path) {
    case '/ledger/accounts': return page(account, income)
    case '/ledger/balances': return { items: empty ? [] : [account, income].map((a, i) => ({
      ...a, account_id: a.id, debit_total_minor: i ? 0 : 12500, credit_total_minor: i ? -12500 : 0, balance_minor: i ? -12500 : 12500,
    })), totals: empty ? [] : [{ currency: 'USD', sum_minor: 0 }], truncated: false }
    case '/ledger/transactions': return page(transaction)
    case '/ledger/transactions/txn': return transaction
    case '/ledger/accounts/cash/entries': return page({ ...transaction.entries[0], transaction_id: transaction.id, posted_at: time, description: transaction.description })
    case '/invoices': return page(invoice)
    case '/invoices/invoice-1': return invoice
    case '/invoices/aging': return { currencies: empty ? [] : [{ currency: 'USD', current_minor: 8500, current_count: 2,
      buckets: [{ label: '1–30 days', amount_minor: 12500, count: 1 }], count: 3, total_minor: 21000 }] }
    case '/payouts': return page(payout)
    case '/payouts/totals': return empty ? [] : [{ ...payout, count: 1 }]
    case '/payouts/payout-1': return payout
    case '/reconciliation/runs': return page(run)
    case '/reconciliation/runs/run-1': return run
    case '/reconciliation/runs/run-1/results': return { run, matched: [], matched_total: 0, unmatched_lines: [], unmatched_entries: [],
      entries_truncated: false, summary: { statement_total_minor: 5000, difference_minor: 5000 } }
    case '/location/positions': return { ...page(position), truncated: false }
    case '/location/positions/courier-17': return position
    case '/location/positions/courier-17/history': return { ...page(position), retention_cap: 100 }
    case '/geo/places': return page({ ...position, id: 'depot', name: 'Central depot', kind: 'depot' })
    case '/geo/geofences': return page({ id: 'fence', shape: 'circle', name: 'City centre', center: position, radius_m: 135, vertices: null })
    case '/matching/assignments':
    case '/geo/events': return page()
    case '/booking/resources': return page(resource)
    case '/booking/resources/room-1': return resource
    case '/booking/resources/room-1/availability': return { slots: empty ? [] : slots, resource_id: resource.id, timezone: 'UTC', slot_minutes: 30 }
    case '/booking/bookings': return page(booking)
    case '/booking/bookings/booking-1': return booking
    default: return undefined
  }
}
