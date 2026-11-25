import type { JsonSchema } from '../../../../forms/types'
import type { PackAddress, PackBlock } from '../api/packs'
import { packRanges } from '../../../validators'

export type PackId = 'ledgersettings' | 'currencysettings' | 'reconsettings' | 'invoicingsettings' |
  'bookingsettings' | 'geosettings' | 'locationsettings'
type Fields = Record<string, JsonSchema>
export type PackDefinition = {
  address: PackAddress
  defaults: PackBlock
  groups: Record<string, JsonSchema>
  roles?: string[]
  prerequisites?: PackId[]
  dependants?: { address: PackAddress; key: string }[]
  links: string[]
}

const object = (properties: Fields): JsonSchema => ({ type: 'object', properties })
const text = (value?: string): JsonSchema => ({ type: 'string', default: value })
const integer = (value: number): JsonSchema => ({ type: 'integer', default: value })
const boolean = (value: boolean): JsonSchema => ({ type: 'boolean', default: value })
const optional = (properties: Fields): JsonSchema => ({
  anyOf: [object(properties), { type: 'null' }], 'x-ui': { optional: true },
})
const roleFields = (...roles: string[]): Fields => Object.fromEntries(roles.map(role => [role, { type: 'array' }]))
const roleDefaults = (...roles: string[]) => Object.fromEntries(roles.map(role => [role, ['admin']]))
const fieldGroups = (groups: Record<string, Fields>) => Object.fromEntries(
  Object.entries(groups).map(([name, fields]) => [name, object(fields)]),
)
const limits = (group: keyof typeof packRanges, defaults: Record<string, number>) => Object.fromEntries(
  Object.keys(packRanges[group]).map(field => [field, integer(defaults[field])]),
)
const readWrite = ['read_roles', 'write_roles']
const moneyNeeds: PackId[] = ['currencysettings', 'ledgersettings']
const moneyDependants: NonNullable<PackDefinition['dependants']> = [
  { address: ['money', 'reconciliation'], key: 'reconDepends' },
  { address: ['money', 'invoicing'], key: 'invoiceDepends' },
]
const accounts = {
  receivable_account: 'receivables', payable_account: 'payables', revenue_account: 'revenue',
  expense_account: 'expenses', tax_account: 'tax', cash_account: 'bank',
}
const invoiceAccounts = Object.fromEntries(Object.entries(accounts).map(([key, value]) => [key, text(value)]))
const geoDefaults = { grid_cell_micro: 10000, max_places: 100000, max_geofences: 1000, max_polygon_vertices: 200, max_radius_m: 20000000 }
const locationDefaults = { history_cap: 100, max_subjects: 100000 }
const bookingRoles = ['read_roles', 'book_roles', 'manage_roles']
const cancellation = { free_until_hours: 24, fee_minor: 0, currency: 'USD' }
export const bookingKindDefaults = { name: '', mode: 'slot', timezone: 'UTC', slot_minutes: 30, schedule: {},
  capacity: 1, min_minutes: 15, max_minutes: 43200 }

const showMode = (field: JsonSchema, ...modes: string[]): JsonSchema => ({ ...field, 'x-ui': { showWhen: { field: 'mode', in: modes } } })
const kinds: JsonSchema = {
  type: 'array', maxItems: 20, 'x-ui': { itemLabel: 'Kind' }, items: {
    ...object({
      name: text(''), mode: { ...text('slot'), enum: ['slot', 'range', 'pool'] }, timezone: text('UTC'),
      slot_minutes: showMode(integer(30), 'slot'), schedule: showMode({ type: 'object', default: {} }, 'slot'),
      capacity: showMode(integer(1), 'pool'), min_minutes: showMode(integer(15), 'range', 'pool'),
      max_minutes: showMode(integer(43200), 'range', 'pool'),
    }),
    default: bookingKindDefaults,
  },
}

export function changeBookingMode(value: PackBlock, mode: string) {
  return {
    ...value, mode,
    ...(mode === 'slot' ? { min_minutes: bookingKindDefaults.min_minutes, max_minutes: bookingKindDefaults.max_minutes }
      : { slot_minutes: bookingKindDefaults.slot_minutes, schedule: {} }),
    ...(mode === 'pool' ? {} : { capacity: bookingKindDefaults.capacity }),
  }
}

export const packDefinitions: Record<PackId, PackDefinition> = {
  ledgersettings: {
    address: ['money', 'ledger'], roles: ['read_roles', 'post_roles'], prerequisites: ['currencysettings'],
    defaults: { ...roleDefaults('read_roles', 'post_roles'), max_amount_minor: Number.MAX_SAFE_INTEGER, max_entries: 100 },
    groups: fieldGroups({ access: roleFields('read_roles', 'post_roles'), posting: { max_amount_minor: integer(Number.MAX_SAFE_INTEGER), max_entries: integer(100) } }),
    dependants: moneyDependants, links: ['ledger'],
  },
  currencysettings: {
    address: ['money', 'currency'], defaults: { currencies: ['USD'], rounding: 'half_even', tax: null },
    groups: fieldGroups({ currencies: { currencies: { type: 'array' } },
      rounding: { rounding: { ...text('half_even'), enum: ['half_even'] } },
      tax: { tax: optional({ rates_bp: { type: 'object', default: {} } }) } }),
    dependants: [{ address: ['money', 'ledger'], key: 'ledgerNeedsCurrency' },
      { address: ['money', 'reconciliation'], key: 'reconNeedsCurrency' },
      { address: ['money', 'invoicing'], key: 'invoiceNeedsCurrency' }], links: [],
  },
  reconsettings: {
    address: ['money', 'reconciliation'], roles: ['read_roles', 'run_roles'], prerequisites: moneyNeeds,
    defaults: { ...roleDefaults('read_roles', 'run_roles'), tolerance_minor: 0, max_lines: 1000 },
    groups: fieldGroups({ access: roleFields('read_roles', 'run_roles'),
      matching: { tolerance_minor: integer(0), max_lines: integer(1000) } }), links: ['reconciliation'],
  },
  invoicingsettings: {
    address: ['money', 'invoicing'], roles: readWrite, prerequisites: moneyNeeds,
    defaults: { ...roleDefaults(...readWrite), number_prefix: 'INV-', payment_terms_days: 30,
      ...accounts, aging_buckets_days: [30, 60, 90], payouts: null },
    groups: fieldGroups({ access: roleFields(...readWrite),
      numbering: { number_prefix: text('INV-'), payment_terms_days: integer(30), aging_buckets_days: { type: 'array' } },
      accounts: invoiceAccounts, payouts: { payouts: optional({
        commission_bp: integer(1000), seller_payable_account: text('seller_payable'), commission_account: text('commission'),
      }) } }),
    dependants: [], links: ['invoices', 'payouts'],
  },
  bookingsettings: {
    address: ['booking'], roles: bookingRoles,
    defaults: { ...roleDefaults(...bookingRoles), kinds: [], hold_ttl_seconds: 600, max_horizon_days: 365, cancellation, own_only: false },
    groups: fieldGroups({ kinds: { kinds }, bookingWindow: { hold_ttl_seconds: integer(600), max_horizon_days: integer(365) },
      cancellation: { cancellation: object({ free_until_hours: integer(24), fee_minor: integer(0), currency: text('USD') }) },
      access: { ...roleFields(...bookingRoles), own_only: boolean(false) } }), links: ['bookings', 'bookingadmin'],
  },
  geosettings: {
    address: ['operations', 'geo'], roles: readWrite,
    defaults: { ...roleDefaults(...readWrite), provider: 'fake', ...geoDefaults },
    groups: fieldGroups({ access: roleFields(...readWrite), index: limits('geo', geoDefaults) }),
    dependants: [{ address: ['operations', 'location'], key: 'geoDepends' }], links: ['places', 'locationsettings'],
  },
  locationsettings: {
    address: ['operations', 'location'], roles: readWrite,
    defaults: { ...roleDefaults(...readWrite), ...locationDefaults },
    groups: fieldGroups({ access: roleFields(...readWrite), retention: limits('location', locationDefaults) }),
    dependants: [{ address: ['operations', 'matching'], key: 'locationDepends' }], links: ['places', 'geosettings'],
  },
}
