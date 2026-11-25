import type { ReactNode } from 'react'
import { useLanguage, useT } from '../../../i18n'
import { Alert, Badge, Card, Disclosure, Row, Stack, Table } from '../../../ui'
import { packCurrencyExponents } from '../../../validators'
import type { PackBlock } from '../api/packs'
import { packDefinitions } from '../state/packs'
import type { PackId } from '../state/packs'
import { SectionLink } from './BlockStatus'
import { PackSummary } from './PackFields'

type Availability = { section: string; ready?: boolean }
type Props = {
  projectId: string; screen: PackId; draft: PackBlock | null; roles: { name: string; label: string }[]
  prerequisites: Availability[]; related: Availability[]; ceiling: number
  version: number; row: number; updated: string | null; geo: boolean
}

const stringList = (value: unknown) => Array.isArray(value) ? value as string[] : []
const asBlock = (value: unknown) => value as PackBlock | null
const summaries: Record<PackId, string[]> = {
  ledgersettings: ['max_amount_minor', 'max_entries'],
  currencysettings: [],
  reconsettings: ['tolerance_minor', 'max_lines'],
  invoicingsettings: ['number_prefix', 'payment_terms_days', 'aging_buckets_days'],
  bookingsettings: ['hold_ttl_seconds', 'max_horizon_days'],
  geosettings: ['max_places', 'max_geofences', 'max_polygon_vertices', 'max_radius_m'],
  locationsettings: ['history_cap', 'max_subjects'],
}

export function PackReference({ projectId, screen, draft, roles, prerequisites, related, ceiling, version, row, updated, geo }: Props) {
  const { t, language } = useLanguage()
  const definition = packDefinitions[screen]
  const link = (section: string) => <SectionLink key={section} projectId={projectId} section={section} label={t('nav.' + section)} />
  const date = updated && !Number.isNaN(Date.parse(updated)) ? new Intl.DateTimeFormat(language, {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date(updated)) : null
  const label = (field: string) => t('connectC.field.' + field)
  const value = (value: unknown) => typeof value === 'number' || typeof value === 'string'
    ? t('connectC.value', { value }) : t('connectC.unset')
  const statusList = (items: Availability[], required = false) => <Stack gap={2}>{items.map(({ section, ready }) =>
    <Row key={section}>{link(section)}{ready != null && <Badge tone={ready ? 'success' : 'neutral'}>
      {t(ready ? required ? 'connectC.ready' : 'connectC.on' : required ? 'connectC.required' : 'connectC.off')}
    </Badge>}</Row>)}</Stack>
  const amounts: [string, ReactNode][] = summaries[screen].map(field => [
    label(field), value(Array.isArray(draft?.[field]) ? (draft[field] as unknown[]).map(value).join(', ') : draft?.[field]),
  ])
  if (screen === 'reconsettings') amounts.push([t('connectC.toleranceCeiling'), value(ceiling)], [t('connectC.entriesConsidered'), value(5000)])
  if (screen === 'geosettings' && typeof draft?.grid_cell_micro === 'number') {
    const degrees = new Intl.NumberFormat(language, { maximumFractionDigits: 6 }).format(draft.grid_cell_micro / 1_000_000)
    amounts.unshift([t('connectC.cellSize'), t('connectC.degrees', { value: degrees })])
  }
  if (screen === 'locationsettings' && Number.isSafeInteger(draft?.history_cap) && Number.isSafeInteger(draft?.max_subjects)) {
    const capacity = BigInt(draft!.history_cap as number) * BigInt(draft!.max_subjects as number)
    amounts.push([t('connectC.historyCapacity'), t('connectC.rows', { value: capacity.toLocaleString(language) })])
  }
  if (screen === 'bookingsettings') {
    amounts.unshift([label('kinds'), value(Array.isArray(draft?.kinds) ? draft.kinds.length : 0)])
    const cancellation = asBlock(draft?.cancellation)
    const currency = cancellation?.currency
    if (typeof currency === 'string' && typeof cancellation?.fee_minor === 'number') {
      const decimals = Object.hasOwn(packCurrencyExponents, currency) ? packCurrencyExponents[currency] : null
      const fee = decimals == null ? t('connectC.minorFee', { value: cancellation.fee_minor, currency }) :
        new Intl.NumberFormat(language, { style: 'currency', currency, maximumFractionDigits: decimals, minimumFractionDigits: decimals })
          .format(cancellation.fee_minor / 10 ** decimals)
      amounts.push([label('fee_minor'), t('connectC.value', { value: fee })])
    }
  }
  const accounts = screen === 'invoicingsettings' && draft ? Object.entries({
    ...draft, ...asBlock(draft.payouts),
  }).filter(([field]) => field.endsWith('_account')).map(([field, code]): [string, ReactNode] => [label(field), value(code)]) : []
  const rates = screen === 'currencysettings' && draft?.tax ? Object.entries(asBlock(asBlock(draft.tax)?.rates_bp) ?? {}) : []
  return <aside aria-label={t('connectC.reference')}><Stack>
    {prerequisites.length > 0 && <Card><Stack><h2>{t('connectC.prerequisites')}</h2>{statusList(prerequisites, true)}</Stack></Card>}
    {draft && <Card><Stack>
      <h2>{t('connectC.screen.' + screen + '.reference')}</h2>
      <p>{t('connectC.screen.' + screen + '.summary')}</p>
      {screen === 'locationsettings' && <p>{t(geo ? 'connectC.geofencesOn' : 'connectC.geofencesOff')}</p>}
      {amounts.length > 0 && <PackSummary title={t('connectC.currentLimits')} items={amounts} />}
      {accounts.length > 0 && <PackSummary title={t('connectC.group.accounts')} items={accounts} />}
      {rates.length > 0 && <PackSummary title={label('tax')} items={rates.map(([name, rate]) => [value(name),
        typeof rate === 'number' ? t('connectC.taxSummary', { bp: rate,
          rate: new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 2 }).format(rate / 10_000),
        }) : value(rate),
      ])} />}
      {screen === 'invoicingsettings' && draft.payouts != null && <p>{t('connectC.payoutsOn', {
        value: value(asBlock(draft.payouts)?.commission_bp),
      })}</p>}
      {definition.links.length > 0 && <Row>{definition.links.map(link)}</Row>}
    </Stack></Card>}
    {related.length > 0 && <Card><Stack><h2>{t('connectC.related')}</h2>{statusList(related)}</Stack></Card>}
    {draft && definition.roles && <Card><Disclosure label={t('connectC.matrix')}>
      <RoleMatrix draft={draft} fields={definition.roles} roles={roles} />
    </Disclosure></Card>}
    <Card><Stack>
      <h2>{t('connectC.projectSpec')}</h2>
      <p>{t('connectA2.version', { version, row })}</p>
      <p className="v2-muted">{date ? t('connectA2.updated', { date }) : t('connectC.noSavedPacks')}</p>
      <Row>{link('timeline')}{link('specdiff')}</Row>
    </Stack></Card>
  </Stack></aside>
}

function RoleMatrix({ draft, fields, roles }: { draft: PackBlock; fields: string[]; roles: Props['roles'] }) {
  const t = useT()
  const names = new Map(roles.map(role => [role.name, role.label || role.name]))
  for (const field of fields) for (const role of stringList(draft[field])) if (!names.has(role)) names.set(role, role)
  const label = t('connectC.matrix')
  const booking = fields.includes('manage_roles')
  const routeFields = booking ? ['visibility', 'book_roles', 'manage_roles'] : fields
  function rights(role: string) {
    const accepts = (field: string) => stringList(draft[field]).length === 0 || stringList(draft[field]).includes(role)
    const state = (allowed: boolean) => t(allowed ? 'connectC.allowed' : 'connectC.restricted')
    if (!booking) return fields.map(field => state(accepts(field)))
    const manages = stringList(draft.manage_roles).includes(role)
    const canManage = accepts('manage_roles')
    const canBook = canManage || accepts('book_roles')
    const canRead = canBook || accepts('read_roles')
    const visibility = manages || canRead && !draft.own_only ? 'all' : canRead ? 'own' : 'restricted'
    return [t('connectC.' + visibility), state(canBook), state(canManage)]
  }
  if (!names.size) return <Alert>{t('connectC.noRoles')}</Alert>
  return <Table label={label} columns={[{ id: 'role', label: t('connectC.column.role') }, ...routeFields.map(field => ({
    id: field, label: t('connectC.field.' + field),
  }))]} rows={Array.from(names, ([name, roleLabel]) => ({
    id: name, cells: [t('schema.option', { value: roleLabel }), ...rights(name)],
  }))} />
}
