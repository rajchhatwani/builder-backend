import { describe, expect, it } from 'vitest'
import {
  FORBIDDEN_MESSAGE, checkDraft, detailLines, draftFrom, platformError, platformIssues, readApps, readAudit, readCatalogue, readInstalled, readKeyCreated, readKeys,
  shortWhen, toBlock,
} from './platformLogic'

const BLOCK = {
  enabled: true, roles: ['admin'], entities: [{ entity: 'order', fields: ['id', 'total'], sandbox: true }], rate_limit: '60/minute', sandbox_rate_limit: '20/minute',
  key_ttl_days: 30, apps: [{ name: 'crm', title: 'CRM', scopes: ['order'], events: ['order-created'] }], extra: { keep: 1 },
}

describe('draft <-> block', () => {
  it('round-trips and carries unmanaged keys over', () => {
    const out = toBlock(draftFrom(BLOCK), BLOCK)
    expect(out).toEqual(BLOCK)
  })
  it('an empty block gets the server defaults', () => {
    const d = draftFrom(null)
    expect(d).toMatchObject({ enabled: false, roles: [], rateLimit: '60/minute', sandboxRateLimit: '20/minute', ttl: '90' })
    expect(toBlock(d, null)).toMatchObject({ enabled: false, key_ttl_days: 90, entities: [], apps: [] })
  })
  it('ignores junk rows', () => {
    expect(draftFrom({ entities: ['x', null, { entity: 'a', fields: 'no' }] as unknown as never }).entities).toHaveLength(1)
  })
})

describe('checkDraft', () => {
  const good = () => draftFrom(BLOCK)
  it('accepts a good draft', () => expect(checkDraft(good())).toEqual({}))
  it('validates the rate limits like the server', () => {
    for (const bad of ['60', 'fast', '0/minute', '60/week', '60 /minute', '/minute', '60/']) {
      const d = good(); d.rateLimit = bad
      expect(checkDraft(d).rateLimit, bad).toBeTruthy()
    }
    for (const okv of ['60/minute', '5/second', '1000/hour', '5/2hours', '10/day']) {
      const d = good(); d.rateLimit = okv; d.sandboxRateLimit = okv
      expect(checkDraft(d), okv).toEqual({})
    }
  })
  it('validates key lifetime 1..365', () => {
    for (const t of ['0', '366', 'x', '', '1.5']) { const d = good(); d.ttl = t; expect(checkDraft(d).ttl, t).toBeTruthy() }
    for (const t of ['1', '365']) { const d = good(); d.ttl = t; expect(checkDraft(d).ttl, t).toBeUndefined() }
  })
  it('needs entity names, fields, no duplicates', () => {
    const d = good()
    d.entities = [{ k: 1, entity: '', fields: [], sandbox: false }, { k: 2, entity: 'a', fields: ['x', 'x'], sandbox: false }, { k: 3, entity: 'a', fields: ['y'], sandbox: false }]
    const e = checkDraft(d)
    expect(e['ent.1.entity']).toBeTruthy(); expect(e['ent.1.fields']).toBeTruthy(); expect(e['ent.2.fields']).toBeTruthy(); expect(e['ent.3.entity']).toContain('twice')
  })
  it('validates apps: slug, unique, scopes, event slugs', () => {
    const d = good()
    d.apps = [{ k: 1, name: 'Bad Name', title: '', scopes: [], events: ['ok', 'Not Slug'] }, { k: 2, name: 'a', title: '', scopes: ['x'], events: [] }, { k: 3, name: 'a', title: '', scopes: ['x'], events: [] }]
    const e = checkDraft(d)
    expect(e['app.1.name']).toBeTruthy(); expect(e['app.1.scopes']).toBeTruthy(); expect(e['app.1.events']).toBeTruthy(); expect(e['app.3.name']).toContain('twice')
  })
})

describe('server issue helpers', () => {
  it('keeps only api_platform issues', () => {
    expect(platformIssues([{ path: 'api_platform.roles', message: 'm' }, { path: 'compliance', message: 'x' }, { path: 'api_platform', message: 'n' }])).toEqual(['api_platform.roles: m', 'api_platform: n'])
  })
  it('reads 422 details of several shapes', () => {
    expect(detailLines(['a', { path: 'p', message: 'm' }, { loc: ['body', 'x'], msg: 'bad' }, 5])).toEqual(['a', 'p: m', 'body.x: bad'])
  })
})

describe('answer shape guards', () => {
  it('catalogue', () => {
    expect(readCatalogue({ entities: [{ entity: 'order', plural_path: 'orders', fields: ['id'], sandbox: true }], rate_limit: '1/second', sandbox_rate_limit: '1/second', key_ttl_days: 90 })?.entities[0]).toEqual({ entity: 'order', fields: ['id'], sandbox: true })
    expect(readCatalogue({ items: [] })).toBeNull(); expect(readCatalogue([])).toBeNull(); expect(readCatalogue({ entities: [{}] })).toBeNull()
  })
  it('keys', () => {
    const k = { id: 'k1', name: 'n', prefix: 'pk_1', kind: 'key', app: null, environment: 'prod', scopes: ['order'], created_at: '', expires_at: '', revoked_at: null, last_used_at: null, status: 'active' }
    expect(readKeys([k])?.[0].status).toBe('active')
    expect(readKeys([{ ...k, status: 'weird' }])).toBeNull(); expect(readKeys({})).toBeNull()
  })
  it('created key and installed app need the one-time secret', () => {
    expect(readKeyCreated({ id: 'k', name: 'n', key: 'sk_x' })?.key).toBe('sk_x')
    expect(readKeyCreated({ id: 'k', name: 'n' })).toBeNull(); expect(readKeyCreated({ id: 'k', key: '' })).toBeNull()
    expect(readInstalled({ app: 'crm', token: 't', signing_secret: 's', granted_scopes: ['a'] })?.signing_secret).toBe('s')
    expect(readInstalled({ app: 'crm', token: 't' })).toBeNull()
  })
  it('apps and audit', () => {
    expect(readApps([{ name: 'crm', title: '', scopes: ['a'], events: [], installed: false }])?.[0].title).toBe('crm')
    expect(readApps([{ title: 'x' }])).toBeNull(); expect(readApps({})).toBeNull()
    expect(readAudit([{ id: 'a', at: '2026-01-01T00:00:00Z', actor: 'u', action: 'key.create', target: null, detail: { x: 1 } }])?.[0].detail).toEqual({ x: 1 })
    expect(readAudit([{ id: 'a' }])).toBeNull()
  })
})

describe('platformError', () => {
  it('403 names api_platform.roles', () => {
    expect(platformError(403, { message: 'forbidden' })).toBe(FORBIDDEN_MESSAGE)
    expect(FORBIDDEN_MESSAGE).toContain('api_platform.roles')
    expect(FORBIDDEN_MESSAGE).toContain('preview')
  })
  it('others show the server message, with fallbacks', () => {
    expect(platformError(409, { message: 'name taken' })).toBe('name taken')
    expect(platformError(422, { detail: 'bad scope' })).toBe('bad scope')
    expect(platformError(500, null)).toContain('500')
    expect(platformError(401, {})).toContain('Sign in')
  })
  it('formats instants', () => { expect(shortWhen('2026-03-04T05:06:07Z')).toBe('2026-03-04 05:06 UTC'); expect(shortWhen(null)).toBe('') })
})
