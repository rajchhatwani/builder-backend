import { act, createElement, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { SchemaForm } from './SchemaForm'
import { MAX_DEPTH, TOO_DEEP_MSG, defaultFor, issuesFromDetail, resolve, scalarHint, validateValue } from './schemaLogic'
import type { JsonSchema, PathErrors } from './types'
import observability from './schemas/observability.json'
import lists from './schemas/lists.json'
import storage from './schemas/storage.json'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null
let host: HTMLElement
let latest: unknown
afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
})

async function mount(schema: JsonSchema, initial: unknown, props: { externalErrors?: PathErrors; readOnly?: boolean } = {}) {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  function Harness() {
    const [v, setV] = useState(initial)
    latest = v
    return createElement(SchemaForm, { schema, value: v, onChange: (n: unknown) => { latest = n; setV(n) }, idPrefix: 't', ...props })
  }
  await act(async () => root!.render(createElement(Harness)))
}
const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T>(sel)
const byLabel = (text: string) => {
  const l = [...host.querySelectorAll('label')].find((x) => x.textContent?.replace(/\s*\*$/, '') === text)
  if (!l) throw new Error(`no label ${text}`)
  return host.querySelector<HTMLInputElement & HTMLSelectElement>(`#${CSS.escape(l.htmlFor)}`)!
}
const setText = async (el: HTMLInputElement | HTMLSelectElement, v: string) => {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, v)
    el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
}
const click = (el: Element) => act(async () => { (el as HTMLElement).click() })
const blur = (el: HTMLElement) => act(async () => { el.focus(); el.blur() })
const button = (name: string) => [...host.querySelectorAll('button')].find((b) => b.getAttribute('aria-label') === name || b.textContent === name) as HTMLButtonElement

const obs = observability as JsonSchema
const lst = lists as JsonSchema
const sto = storage as JsonSchema

describe('field types', () => {
  it('renders string, integer, number, boolean and labels from titles', async () => {
    const schema: JsonSchema = {
      type: 'object', required: ['name'],
      properties: {
        name: { type: 'string', title: 'Display name', description: 'Shown to users' },
        count: { type: 'integer', title: 'Count' },
        ratio: { type: 'number', title: 'Ratio' },
        on: { type: 'boolean', title: 'On' },
      },
    }
    await mount(schema, { name: '' })
    expect(byLabel('Display name').type).toBe('text')
    expect(byLabel('Count').type).toBe('number')
    expect(byLabel('Count').step).toBe('1')
    expect(byLabel('Ratio').step).toBe('any')
    expect(byLabel('On').type).toBe('checkbox')
    expect(q('#t-name-help')?.textContent).toBe('Shown to users')
    expect(byLabel('Display name').getAttribute('aria-describedby')).toBe('t-name-help')
    await setText(byLabel('Count'), '7')
    await setText(byLabel('Ratio'), '0.25')
    await click(byLabel('On'))
    expect(latest).toEqual({ name: '', count: 7, ratio: 0.25, on: true })
  })

  it('renders an enum as a select; nullable fields offer a blank option', async () => {
    await mount(sto, defaultFor(sto, sto))
    const backend = byLabel('Backend') as HTMLSelectElement
    expect([...backend.options].map((o) => o.value)).toEqual(['s3', 'minio'])
    await setText(backend, 'minio')
    expect((latest as { backend: string }).backend).toBe('minio')
    const quota = byLabel('User quota mb')
    expect(quota.type).toBe('number')
    await setText(quota, '5')
    await setText(quota, '')
    expect((latest as { user_quota_mb: unknown }).user_quota_mb).toBeNull()
  })

  it('csv widget edits an array of strings', async () => {
    await mount(sto, defaultFor(sto, sto))
    await setText(byLabel('Allowed types'), 'image/png, application/pdf,')
    expect((latest as { allowed_types: string[] }).allowed_types).toEqual(['image/png', 'application/pdf'])
  })
})

describe('required and client hints', () => {
  const schema: JsonSchema = {
    type: 'object', required: ['name'],
    properties: {
      name: { type: 'string', title: 'Name', minLength: 1, maxLength: 5, pattern: '^[a-z]+$' },
      n: { type: 'integer', title: 'N', minimum: 1, maximum: 10 },
    },
  }
  it('marks required fields, and shows a hint only after blur, in the backend wording', async () => {
    await mount(schema, { name: '' })
    const name = byLabel('Name')
    expect(name.getAttribute('aria-required')).toBe('true')
    expect(name.getAttribute('aria-invalid')).toBeNull()
    await blur(name)
    expect(name.getAttribute('aria-invalid')).toBe('true')
    expect(q('#t-name-err')?.textContent).toBe('Field required')
    await setText(name, 'abcdefg')
    expect(q('#t-name-err')?.textContent).toBe('String should have at most 5 characters')
    await setText(name, 'AB')
    expect(q('#t-name-err')?.textContent).toBe("String should match pattern '^[a-z]+$'")
  })
  it('checks min and max of numbers', () => {
    expect(validateValue(schema, schema, { name: 'ok', n: 0 })).toEqual({ n: ['Input should be greater than or equal to 1'] })
    expect(validateValue(schema, schema, { name: 'ok', n: 11 })).toEqual({ n: ['Input should be less than or equal to 10'] })
    expect(validateValue(schema, schema, { name: 'ok', n: 3 })).toEqual({})
  })
  it('checks list sizes with the backend wording', () => {
    const s: JsonSchema = { type: 'object', properties: { a: { type: 'array', items: { type: 'string' }, maxItems: 1 } } }
    expect(validateValue(s, s, { a: ['x', 'y'] })).toEqual({ a: ['List should have at most 1 item after validation, not 2'] })
  })
})

describe('show-when', () => {
  it('hides dependent fields until the sibling matches, and keeps their value', async () => {
    await mount(obs, { ...(defaultFor(obs, obs) as object), enabled: true, service_name: 'svc' })
    expect(q('#t-service_name')).not.toBeNull()
    await click(byLabel('Enabled'))
    expect(q('#t-service_name')).toBeNull()
    expect((latest as { service_name: string }).service_name).toBe('svc')
    await click(byLabel('Enabled'))
    expect(byLabel('Service name').value).toBe('svc')
  })
  it('shows region only for the s3 backend', async () => {
    await mount(sto, defaultFor(sto, sto))
    expect(q('#t-region')).not.toBeNull()
    await setText(byLabel('Backend'), 'minio')
    expect(q('#t-region')).toBeNull()
  })
  it('does not validate hidden fields', () => {
    const v = { ...(defaultFor(obs, obs) as object), enabled: false, sample_ratio: 5000 }
    expect(validateValue(obs, obs, v)).toEqual({})
  })
})

describe('nested objects', () => {
  it('renders nested groups as fieldsets and edits deep values', async () => {
    await mount(sto, defaultFor(sto, sto))
    const sec = q<HTMLFieldSetElement>('fieldset[data-field-path="security"]')!
    expect(sec.querySelector('legend')?.textContent).toBe('Security')
    await setText(byLabel('Audit retention days'), '30')
    expect((latest as { security: { audit_retention_days: number } }).security.audit_retention_days).toBe(30)
    expect((latest as { security: { audit_ip: boolean } }).security.audit_ip).toBe(true)
  })
})

describe('arrays of objects', () => {
  const start = () => defaultFor(lst, lst)
  it('adds, edits, reorders and removes rows', async () => {
    await mount(lst, start())
    expect(q('[data-array-item]')).toBeNull()
    await click(button('Add list'))
    await click(button('Add list'))
    expect(host.querySelectorAll('[data-array-item="0"], [data-array-item="1"]').length).toBe(2)
    await setText(byLabel('Name') as HTMLInputElement, 'first') // first match: row 1
    const names = () => ((latest as { lists: { name: string }[] }).lists).map((l) => l.name)
    expect(names()).toEqual(['first', ''])
    await click(button('Move List 1 down'))
    expect(names()).toEqual(['', 'first'])
    expect(button('Move List 1 up').disabled).toBe(true)
    await click(button('Remove List 1'))
    expect(names()).toEqual(['first'])
    await click(button('Remove List 1'))
    expect(names()).toEqual([])
  })
  it('adds nested rows inside a row', async () => {
    await mount(lst, start())
    await click(button('Add list'))
    await click(button('Add item'))
    const l = (latest as { lists: { items: unknown[] }[] }).lists
    expect(l[0].items).toHaveLength(1)
    expect(button('Remove Item 1')).toBeTruthy()
  })
  it('moves focus sensibly: new row, then the add button after the last remove', async () => {
    await mount(lst, start())
    await click(button('Add list'))
    expect((document.activeElement as HTMLElement | null)?.closest('[data-array-item="0"]')).not.toBeNull()
    button('Remove List 1').focus()
    await click(button('Remove List 1'))
    expect(document.activeElement).toBe(button('Add list'))
  })
  it('rows are real buttons, so Enter and Space work (type=button, no form submit)', async () => {
    await mount(lst, start())
    for (const b of host.querySelectorAll('button')) expect(b.type).toBe('button')
  })
})

describe('readOnly', () => {
  it('locks inputs and removes add/remove controls', async () => {
    await mount(lst, { lists: [{ name: 'a', items: [] }] }, { readOnly: true })
    expect((byLabel('Name') as HTMLInputElement).readOnly).toBe(true)
    expect(host.querySelectorAll('button').length).toBe(0)
    await mount(sto, defaultFor(sto, sto), { readOnly: true })
    expect((byLabel('Backend') as HTMLSelectElement).disabled).toBe(true)
  })
})

describe('external (backend) errors', () => {
  it('maps 422 detail to paths and keeps the text verbatim', () => {
    const e = issuesFromDetail([
      { loc: ['body', 'lists', 0, 'items', 1, 'value'], msg: 'String should have at most 80 characters' },
      { loc: ['body'], msg: 'Value error, custom' },
    ])
    expect(e).toEqual({ 'lists.0.items.1.value': ['String should have at most 80 characters'], '': ['Value error, custom'] })
    expect(issuesFromDetail('nope')).toEqual({})
  })
  it('shows the backend message next to the field and wins over the client hint', async () => {
    const value = { ...(defaultFor(sto, sto) as object), bucket: 'x'.repeat(70) }
    await mount(sto, value, { externalErrors: { bucket: ['Backend says: bucket name is not valid'] } })
    const bucket = byLabel('Bucket')
    await blur(bucket)
    expect(bucket.getAttribute('aria-invalid')).toBe('true')
    expect(bucket.getAttribute('aria-describedby')).toBe('t-bucket-err')
    const err = q('#t-bucket-err')!
    expect(err.textContent).toBe('Backend says: bucket name is not valid')
    expect(err.getAttribute('data-testid')).toBe('field-error')
    expect(q('[data-testid="form-issue-summary"]')?.textContent).toContain('found 1 problem')
  })
  it('maps errors on array rows and group paths', async () => {
    const value = { lists: [{ name: 'a', items: [{ value: 'v', label: 'l' }] }] }
    await mount(lst, value, {
      externalErrors: { 'lists.0.items.0.value': ['String should have at most 80 characters'], 'lists.0': ['Row problem'] },
    })
    expect(q('#t-lists-0-items-0-value-err')?.textContent).toBe('String should have at most 80 characters')
    expect(q('[data-array-item="0"] [data-testid="group-error"]')?.textContent).toBe('Row problem')
    expect(host.querySelectorAll('[data-testid="form-issue-summary"]').length).toBe(1)
  })
})

describe('accessibility attributes', () => {
  it('every control has a label and error text is linked by aria-describedby', async () => {
    await mount(sto, defaultFor(sto, sto), { externalErrors: { max_file_mb: ['Input should be greater than or equal to 1'] } })
    for (const el of host.querySelectorAll('input, select, textarea')) {
      expect(host.querySelector(`label[for="${el.id}"]`), el.id).not.toBeNull()
    }
    const f = byLabel('Max file mb')
    expect(f.getAttribute('aria-invalid')).toBe('true')
    expect(host.querySelector(`#${f.getAttribute('aria-describedby')}`)?.textContent).toBe('Input should be greater than or equal to 1')
    expect(byLabel('Bucket').getAttribute('aria-invalid')).toBeNull()
  })
  it('array rows and buttons have accessible names', async () => {
    await mount(lst, { lists: [{ name: 'a', items: [] }] })
    expect(q('[data-array-item="0"]')?.getAttribute('aria-label')).toBe('List 1')
    expect(button('Remove List 1').getAttribute('aria-label')).toBe('Remove List 1')
  })
})

describe('hardening: untrusted backend locations and schemas', () => {
  const issue = (loc: unknown) => [{ loc, msg: 'bad' }]

  it('issuesFromDetail survives proto-polluting locations without touching Object.prototype', () => {
    for (const loc of [['body', '__proto__'], ['body', 'a', '__proto__', 'b'], ['body', 'constructor', 'prototype'], ['body', 'constructor']]) {
      const out = issuesFromDetail(issue(loc))
      expect(Object.keys(out)).toHaveLength(1)
      expect(Object.values(out)[0]).toEqual(['bad'])
    }
    expect(({} as Record<string, unknown>).bad).toBeUndefined()
    expect(Object.getPrototypeOf(issuesFromDetail([]))).toBeNull()
    expect(Array.prototype.hasOwnProperty('bad')).toBe(false)
  })

  it('issuesFromDetail never throws on odd locations', () => {
    const odd = [[], ['body'], [0, 1], [null, {}, undefined, 'x'], 'str', 5, null, ['x'.repeat(100000)], Array.from({ length: 5000 }, (_, i) => i)]
    for (const loc of odd) expect(() => issuesFromDetail(issue(loc))).not.toThrow()
    expect(() => issuesFromDetail([null, 3, 'x', { msg: 5 }])).not.toThrow()
    const key = Object.keys(issuesFromDetail(issue(['x'.repeat(100000)])))[0]
    expect(key.length).toBeLessThanOrEqual(200)
  })

  it('a cyclic $ref resolves to tooDeep and renders an inline message instead of crashing', async () => {
    const cyc: JsonSchema = { $defs: { A: { $ref: '#/$defs/A' } }, type: 'object', properties: { x: { $ref: '#/$defs/A' } } }
    expect(resolve(cyc, cyc.properties!.x).tooDeep).toBe(true)
    expect(() => validateValue(cyc, cyc, { x: 1 })).not.toThrow()
    expect(() => defaultFor(cyc, cyc)).not.toThrow()
    await mount(cyc, {})
    expect(q('[data-testid="schema-too-deep"]')?.textContent).toContain(TOO_DEEP_MSG)
  })

  it('a self-referential object (A.child -> A) is bounded', async () => {
    const rec: JsonSchema = {
      $defs: { A: { type: 'object', properties: { child: { $ref: '#/$defs/A' }, n: { type: 'string' } } } },
      $ref: '#/$defs/A',
    }
    expect(() => defaultFor(rec, rec)).not.toThrow()
    let v: Record<string, unknown> = { n: 'leaf' }
    for (let i = 0; i < 25; i++) v = { child: v, n: '' }
    expect(() => validateValue(rec, rec, v)).not.toThrow()
    await mount(rec, v)
    expect(q('[data-testid="schema-too-deep"]')).not.toBeNull()
  })

  it('20-deep inline nesting renders the too-deep message', async () => {
    let s: JsonSchema = { type: 'string' }
    let v: unknown = 'x'
    for (let i = 0; i < 20; i++) { s = { type: 'object', properties: { k: s } }; v = { k: v } }
    expect(() => validateValue(s, s, v)).not.toThrow()
    await mount(s, v)
    expect(q('[data-testid="schema-too-deep"]')).not.toBeNull()
    expect(MAX_DEPTH).toBe(16)
  })

  it('an invalid pattern is ignored (no throw, no hint)', () => {
    const s = { type: 'string', pattern: '([unclosed' }
    expect(scalarHint(s, 'abc', false)).toBeNull()
  })

  it('a valid pattern still hints on normal input but is skipped above 10k chars', () => {
    const s = { type: 'string', pattern: '^[a-z]+$' }
    expect(scalarHint(s, 'ABC', false)).toContain('should match pattern')
    expect(scalarHint(s, 'A'.repeat(10_001), false)).toBeNull()
  })
})
