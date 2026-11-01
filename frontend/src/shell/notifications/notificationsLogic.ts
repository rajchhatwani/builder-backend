/** Pure helpers for the Notifications page: reading the spec block, placeholder checks, the safe client-side
 *  preview, the preferences matrix and masking. Mirrors the generated app's rules (placeholders `{{ name }}` of
 *  declared variables only, one pass, no expressions) but never evaluates anything. */

export interface NTemplate { channel: string; subject: string; body: string; html: boolean }
export interface NType {
  name: string
  category: 'transactional' | 'optional'
  channels: string[]
  variables: string[]
  templates: NTemplate[]
  default_enabled: boolean
}
export interface NBlock { enabled: boolean; types: NType[] }

const asStr = (v: unknown) => (typeof v === 'string' ? v : '')
const asList = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

/** Reads the `notifications` block from a GET /spec answer; anything malformed is skipped, never thrown. */
export function readNotifications(spec: unknown): NBlock {
  const raw = (spec && typeof spec === 'object' ? (spec as Record<string, unknown>).notifications : null) as Record<string, unknown> | null
  if (!raw || typeof raw !== 'object') return { enabled: false, types: [] }
  const types: NType[] = []
  for (const t of Array.isArray(raw.types) ? raw.types : []) {
    if (!t || typeof t !== 'object' || typeof (t as { name?: unknown }).name !== 'string') continue
    const o = t as Record<string, unknown>
    const templates: NTemplate[] = []
    for (const x of Array.isArray(o.templates) ? o.templates : []) {
      if (!x || typeof x !== 'object') continue
      const p = x as Record<string, unknown>
      templates.push({ channel: asStr(p.channel), subject: asStr(p.subject), body: asStr(p.body), html: p.html === true })
    }
    types.push({
      name: o.name as string,
      category: o.category === 'transactional' ? 'transactional' : 'optional',
      channels: asList(o.channels),
      variables: asList(o.variables),
      templates,
      default_enabled: o.default_enabled !== false,
    })
  }
  return { enabled: raw.enabled === true, types }
}

export const PLACEHOLDER = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g

/** Names used as placeholders, in order of first use. */
export function placeholdersOf(text: string): string[] {
  const seen: string[] = []
  for (const m of text.matchAll(PLACEHOLDER)) if (!seen.includes(m[1])) seen.push(m[1])
  return seen
}

export interface TemplateCheck { unknown: string[]; malformed: boolean; ok: boolean }

/** Only `{{ name }}` of a declared variable is allowed. Any other `{{`/`}}` left after removing valid
 *  placeholders (an expression, a filter, a stray brace) is "malformed". */
export function checkTemplate(text: string, variables: string[]): TemplateCheck {
  const unknown = placeholdersOf(text).filter((n) => !variables.includes(n))
  const rest = text.replace(PLACEHOLDER, '')
  const malformed = rest.includes('{{') || rest.includes('}}')
  return { unknown, malformed, ok: unknown.length === 0 && !malformed }
}

export function escapeHtml(v: string): string {
  return v.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

const oneLine = (s: string) => s.replace(/[\u0000-\u001f\u007f\u2028\u2029\u202a-\u202e\u2066-\u2069]+/g, ' ').trim()

/** Sample values: a sentence-like value per variable. Callers may override single entries. */
export function sampleValues(variables: string[], overrides: Record<string, string> = {}): Record<string, string> {
  // Variable names come from the spec: `constructor`, `toString`, `__proto__` must be plain keys, never inherited members.
  const out: Record<string, string> = Object.create(null)
  const own = (k: string) => {
    const o = Object.prototype.hasOwnProperty.call(overrides, k) ? overrides[k] : undefined
    return typeof o === 'string' ? o : undefined
  }
  for (const v of variables) out[v] = own(v) ?? `Sample ${v.replace(/_/g, ' ')}`
  return out
}

/** One-pass substitution (a value that itself looks like `{{ x }}` stays literal). For HTML templates the
 *  VALUES are escaped, as in the generated app. The result is only ever shown as plain text. Unknown
 *  placeholders are left visible so the author sees them. */
export function renderPreview(text: string, values: Record<string, string>, html: boolean): string {
  return text.replace(PLACEHOLDER, (whole, name: string) => {
    if (!Object.prototype.hasOwnProperty.call(values, name) || typeof values[name] !== 'string') return whole
    return html ? escapeHtml(values[name]) : values[name]
  })
}

export function renderSubject(text: string, values: Record<string, string>): string {
  return oneLine(renderPreview(text, values, false))
}

export interface MatrixCell { type: string; channel: string; state: 'locked-on' | 'default-on' | 'default-off' | 'n/a' }

/** Type x channel preferences matrix from the spec defaults. Transactional types are locked on. */
export function preferenceMatrix(types: NType[]): { channels: string[]; rows: { type: NType; cells: MatrixCell[] }[] } {
  const channels = [...new Set(types.flatMap((t) => t.channels))].sort()
  const rows = types.map((type) => ({
    type,
    cells: channels.map<MatrixCell>((channel) => ({
      type: type.name,
      channel,
      state: !type.channels.includes(channel) ? 'n/a' : type.category === 'transactional' ? 'locked-on' : type.default_enabled ? 'default-on' : 'default-off',
    })),
  }))
  return { channels, rows }
}

export const CELL_TEXT: Record<MatrixCell['state'], string> = {
  'locked-on': 'On, locked (required)',
  'default-on': 'On by default, user can opt out',
  'default-off': 'Off by default, user can opt in',
  'n/a': 'Not used',
}

/** Masks an address for display, defensively, even if the log already delivered a masked hint. */
export function maskAddress(a: string): string {
  const s = a.trim()
  if (!s) return '—'
  if (s.includes('*') || s.includes('…')) return s
  const at = s.indexOf('@')
  if (at > 0) return `${s[0]}***${s.slice(at)}`
  if (/^\+?[0-9 ()-]{6,}$/.test(s)) return `${s.slice(0, 3)}***${s.slice(-2)}`
  return `${s.slice(0, 2)}***`
}

export interface DeliveryRow { id: string; type: string; channel: string; status: string; to: string; attempts: number; at: string }

/** Example type used when the spec declares none, so the editor and the journey can be tried. */
export const EXAMPLE_TYPES: NType[] = [
  {
    name: 'order_confirmed', category: 'transactional', channels: ['email', 'sms'], variables: ['customer_name', 'order_number', 'total'],
    templates: [
      { channel: 'email', subject: 'Order {{ order_number }} confirmed', body: 'Hello {{ customer_name }}, we received your order {{ order_number }} for {{ total }}.', html: false },
      { channel: 'sms', subject: '', body: 'Order {{ order_number }} confirmed, total {{ total }}.', html: false },
    ],
    default_enabled: true,
  },
  {
    name: 'weekly_digest', category: 'optional', channels: ['email'], variables: ['customer_name', 'count'],
    templates: [{ channel: 'email', subject: 'Your week', body: 'Hi {{ customer_name }}, you have {{ count }} new items.', html: false }],
    default_enabled: false,
  },
]

export const EXAMPLE_DELIVERIES: DeliveryRow[] = [
  { id: 'ex-1', type: 'order_confirmed', channel: 'email', status: 'sent', to: 'a***@example.com', attempts: 1, at: '2026-01-05T09:30:00Z' },
  { id: 'ex-2', type: 'order_confirmed', channel: 'sms', status: 'failed', to: '+49***21', attempts: 5, at: '2026-01-05T09:31:00Z' },
]

// ---- drafts kept in this browser (the builder has no endpoint that stores the notifications block yet)
export type Drafts = Record<string, NTemplate>
export const draftKey = (projectId: string) => `notif.drafts.${projectId}`
export const tplKey = (type: string, channel: string) => `${type}/${channel}`

export function loadDrafts(projectId: string): Drafts {
  try {
    const v = JSON.parse(localStorage.getItem(draftKey(projectId)) ?? '{}') as unknown
    if (!v || typeof v !== 'object') return {}
    const out: Drafts = {}
    for (const [k, t] of Object.entries(v as Record<string, unknown>)) {
      const p = t as Partial<NTemplate>
      if (typeof p?.body === 'string') out[k] = { channel: asStr(p.channel), subject: asStr(p.subject), body: p.body, html: p.html === true }
    }
    return out
  } catch { return {} }
}

export function saveDrafts(projectId: string, d: Drafts): boolean {
  try { localStorage.setItem(draftKey(projectId), JSON.stringify(d)); return true } catch { return false }
}
