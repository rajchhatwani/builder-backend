import { describe, expect, it } from 'vitest'
import {
  EXAMPLE_TYPES, checkTemplate, escapeHtml, loadDrafts, maskAddress, placeholdersOf, preferenceMatrix, readNotifications,
  renderPreview, renderSubject, sampleValues, saveDrafts,
} from './notificationsLogic'

describe('readNotifications', () => {
  it('returns an empty block for a missing or malformed block', () => {
    expect(readNotifications(null)).toEqual({ enabled: false, types: [] })
    expect(readNotifications({ notifications: 7 })).toEqual({ enabled: false, types: [] })
    expect(readNotifications({ notifications: { types: [1, { nope: true }, { name: 'a' }] } }).types.map((t) => t.name)).toEqual(['a'])
  })
  it('reads types, defaults and templates', () => {
    const b = readNotifications({ notifications: { enabled: true, types: [{ name: 'x', category: 'transactional', channels: ['email'], variables: ['v'], default_enabled: false, templates: [{ channel: 'email', subject: 's', body: 'b {{ v }}', html: true }] }] } })
    expect(b.enabled).toBe(true)
    expect(b.types[0]).toMatchObject({ name: 'x', category: 'transactional', default_enabled: false })
    expect(b.types[0].templates[0]).toEqual({ channel: 'email', subject: 's', body: 'b {{ v }}', html: true })
  })
})

describe('placeholders', () => {
  it('lists names once, tolerating spaces', () => {
    expect(placeholdersOf('{{a}} {{ b }} {{a}}')).toEqual(['a', 'b'])
  })
  it('accepts declared variables only', () => {
    expect(checkTemplate('Hi {{ name }}', ['name']).ok).toBe(true)
    expect(checkTemplate('Hi {{ other }}', ['name'])).toMatchObject({ ok: false, unknown: ['other'] })
  })
  it.each(['{{ 7*7 }}', '{{ name | upper }}', '{% if x %}', '{{ name', 'a }} b'])('flags %s', (t) => {
    const c = checkTemplate(t, ['name'])
    if (t.startsWith('{%')) expect(c.ok).toBe(true) // not a placeholder syntax of this engine: plain text
    else expect(c.ok).toBe(false)
  })
})

describe('renderPreview', () => {
  const vals = { name: '<b>Eve</b>', x: '{{ name }}' }
  it('plain text keeps values as they are, one pass only', () => {
    expect(renderPreview('Hi {{ name }}', vals, false)).toBe('Hi <b>Eve</b>')
    expect(renderPreview('{{ x }}', vals, false)).toBe('{{ name }}')
  })
  it('escapes values for html templates, not the template itself', () => {
    expect(renderPreview('<p>{{ name }}</p>', vals, true)).toBe('<p>&lt;b&gt;Eve&lt;/b&gt;</p>')
    expect(escapeHtml(`"'&`)).toBe('&quot;&#39;&amp;')
  })
  it('leaves unknown placeholders visible and ignores prototype names', () => {
    expect(renderPreview('{{ nope }} {{ constructor }}', vals, false)).toBe('{{ nope }} {{ constructor }}')
  })
  it('one-lines the subject', () => {
    expect(renderSubject('A\r\nBcc: x {{ name }}‮', { name: 'N' })).toBe('A Bcc: x N')
  })
  it('builds sample values with overrides', () => {
    expect(sampleValues(['order_number'], { order_number: '7' })).toEqual({ order_number: '7' })
    expect(sampleValues(['order_number'])).toEqual({ order_number: 'Sample order number' })
  })
})

describe('preferenceMatrix', () => {
  it('locks transactional types and marks unused channels', () => {
    const m = preferenceMatrix(EXAMPLE_TYPES)
    expect(m.channels).toEqual(['email', 'sms'])
    expect(m.rows[0].cells.map((c) => c.state)).toEqual(['locked-on', 'locked-on'])
    expect(m.rows[1].cells.map((c) => c.state)).toEqual(['default-off', 'n/a'])
  })
})

describe('maskAddress', () => {
  it('masks emails, phones and others; keeps already masked values', () => {
    expect(maskAddress('alice@example.com')).toBe('a***@example.com')
    expect(maskAddress('+4912345621')).toBe('+49***21')
    expect(maskAddress('a***@x.org')).toBe('a***@x.org')
    expect(maskAddress('device-token-1')).toBe('de***')
    expect(maskAddress('')).toBe('—')
  })
})

describe('drafts', () => {
  it('round-trips and survives garbage', () => {
    expect(saveDrafts('p1', { 'a/email': { channel: 'email', subject: 's', body: 'b', html: false } })).toBe(true)
    expect(loadDrafts('p1')['a/email'].body).toBe('b')
    localStorage.setItem('notif.drafts.p2', '{bad')
    expect(loadDrafts('p2')).toEqual({})
  })
})

import { renderPreview as rp, sampleValues as sv } from './notificationsLogic'
describe('variables named like Object members (M-2)', () => {
  it('render without throwing, escaped in HTML, and never use inherited members', () => {
    const vars = ['constructor', 'toString', '__proto__', 'hasOwnProperty']
    const values = sv(vars, { constructor: '<b>x</b>' })
    expect(values.constructor).toBe('<b>x</b>')
    expect(values.toString).toBe('Sample toString')
    const out = rp('{{ constructor }} {{ toString }} {{ __proto__ }}', values, true)
    expect(out).toBe('&lt;b&gt;x&lt;/b&gt; Sample toString Sample   proto  ')
    expect(rp('{{ toString }}', {}, true)).toBe('{{ toString }}') // not declared: stays visible
  })
})
