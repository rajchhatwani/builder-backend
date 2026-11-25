import { projectId, time } from './connect-a'

const readers = { read_roles: ['admin'] }
const writers = { ...readers, write_roles: ['admin'] }
export const bookingKind = { name: 'consultation', mode: 'slot', timezone: 'UTC', slot_minutes: 30,
  schedule: { mon: [{ start: '09:00', end: '17:00' }] }, capacity: 1, min_minutes: 15, max_minutes: 43200 }
export const packs = {
  money: {
    ledger: { ...readers, post_roles: ['admin'], max_amount_minor: 9007199254740991, max_entries: 100 },
    currency: { currencies: ['USD', 'JPY'], rounding: 'half_even', tax: { rates_bp: { vat: 2000 } } },
    reconciliation: { ...readers, run_roles: ['admin'], tolerance_minor: 5, max_lines: 1000 },
    invoicing: {
      ...writers, number_prefix: 'INV-', payment_terms_days: 30, receivable_account: 'receivables',
      payable_account: 'payables', revenue_account: 'revenue', expense_account: 'expenses',
      tax_account: 'tax', cash_account: 'bank', aging_buckets_days: [30, 60, 90], payouts: null,
    },
  },
  booking: {
    kinds: [bookingKind, { ...bookingKind, name: 'meeting_room', mode: 'range', schedule: {} }],
    ...readers, book_roles: ['member'], manage_roles: ['admin'], own_only: false,
    hold_ttl_seconds: 600, max_horizon_days: 365, cancellation: { free_until_hours: 24, fee_minor: 1500, currency: 'USD' },
  },
  operations: {
    geo: { ...writers, provider: 'fake', grid_cell_micro: 10000, max_places: 100000,
      max_geofences: 1000, max_polygon_vertices: 200, max_radius_m: 20000000 },
    location: { ...writers, history_cap: 100, max_subjects: 100000 },
    matching: null, prediction: null,
  },
  ai: { gateway: { enabled: false } },
}
export const packRoles = [{ name: 'admin', label: 'Administrator' }, { name: 'member', label: 'Member' }]
export const packSpec = { auth: { enabled: true, roles: packRoles }, authorization: { model: 'rbac' }, entities: [] }
export const packsReply = (value: unknown = packs, version = 3) =>
  ({ project_id: projectId, version, row_version: version + 2, updated_at: time, packs: value })

export const packScreens = {
  ledgersettings: { title: 'Ledger settings', normal: 'Posting limits', path: ['money', 'ledger'] },
  currencysettings: { title: 'Currency settings', normal: 'Currencies', path: ['money', 'currency'] },
  reconsettings: { title: 'Reconciliation settings', normal: 'Automatic matching', path: ['money', 'reconciliation'] },
  invoicingsettings: { title: 'Invoicing settings', normal: 'Numbering and aging', path: ['money', 'invoicing'] },
  bookingsettings: { title: 'Booking settings', normal: 'Bookable kinds', path: ['booking'] },
  geosettings: { title: 'Geo settings', normal: 'Index and limits', path: ['operations', 'geo'] },
  locationsettings: { title: 'Location settings', normal: 'Tracking and retention', path: ['operations', 'location'] },
} as const
