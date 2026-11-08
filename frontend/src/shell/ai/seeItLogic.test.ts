import { describe, expect, it, vi } from 'vitest'
import { acceptance, callPreview, createdId, crudComplete, editedBody, entitiesOf, evidence, exampleBody, forgetTokens, itemPath, judge, previewBase, previewRefusal, rememberToken, tokenFor } from './seeItLogic'

const doc = {
  paths: {
    '/health': { get: { responses: {} } },
    '/posts': {
      get: { responses: {} },
      post: { requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/PostCreate' } } } } },
    },
    '/posts/{item_id}': {
      parameters: [{ name: 'item_id', in: 'path', required: true, schema: { type: 'string' } }],
      get: {}, put: {}, patch: { requestBody: { content: { 'application/json': { schema: { type: 'object', properties: { title: { type: 'string' } } } } } } }, delete: {},
    },
    '/tags': { get: {} },
  },
  components: { schemas: { PostCreate: { type: 'object', required: ['title', 'count'], properties: { title: { type: 'string', minLength: 3 }, count: { type: 'integer' }, extra: { type: 'string' } } } } },
}

describe('entities from OpenAPI', () => {
  it('groups list/create/read/update per collection and skips infrastructure', () => {
    const es = entitiesOf(doc)
    expect(es.map((e) => e.name)).toEqual(['posts', 'tags'])
    const p = es[0]
    expect(crudComplete(p)).toBe(true)
    expect(p.update?.method).toBe('patch')
    expect(p.idParam).toBe('item_id')
    expect(crudComplete(es[1])).toBe(false)
    expect(itemPath(p, 'a b')).toBe('/posts/a%20b')
  })
  it('builds a marked example body from required fields only', () => {
    const p = entitiesOf(doc)[0]
    const b = exampleBody(doc, p.create) as Record<string, unknown>
    expect(b).toEqual({ title: 'pre', count: 0 })
    expect(editedBody({ title: 'preview-data' })).toEqual({ title: 'edited--data' })
    expect(editedBody({ n: 1 })).toEqual({ n: 1 })
  })
})

describe('preview calls', () => {
  it('sends the token only as a header, no credentials, and parses JSON', async () => {
    const f = vi.fn().mockResolvedValue(new Response('{"id":"7"}', { status: 201 }))
    const r = await callPreview({ base: 'http://api.test/previews/abc', token: 'tok_123', method: 'post', path: '/posts', body: { title: 'x' } }, f as never)
    expect(f.mock.calls[0][0]).toBe('http://api.test/previews/abc/posts')
    const init = f.mock.calls[0][1]
    expect(init.headers['X-Preview-Token']).toBe('tok_123')
    expect(init.credentials).toBe('omit')
    expect(init.redirect).toBe('error')
    expect(String(f.mock.calls[0][0])).not.toContain('tok_123')
    expect(r.status).toBe(201)
    expect(createdId(r.json)).toBe('7')
    expect(JSON.stringify(evidence('post', '/posts', { title: 'x' }, r))).not.toContain('tok_123')
  })
  it('refuses paths that leave the preview and explains network errors', async () => {
    const f = vi.fn().mockRejectedValue(new TypeError('x'))
    await expect(callPreview({ base: 'http://a/previews/1', token: 't', method: 'get', path: '//evil.test' }, f as never)).rejects.toThrow('relative')
    await expect(callPreview({ base: 'http://a/previews/1', token: 't', method: 'get', path: '/../x' }, f as never)).rejects.toThrow('relative')
    await expect(callPreview({ base: 'http://a/previews/1', token: 't', method: 'get', path: '/x' }, f as never)).rejects.toThrow('Could not reach')
  })
  it('keeps tokens in memory only', () => {
    rememberToken('p1', 'secret')
    expect(tokenFor('p1')).toBe('secret')
    expect(JSON.stringify(localStorage)).not.toContain('secret')
    forgetTokens()
    expect(tokenFor('p1')).toBeNull()
  })
  it('builds the base from the builder URL and the server path', () => {
    expect(previewBase('http://api.test/', '/previews/abc/')).toBe('http://api.test/previews/abc')
    expect(() => previewBase('http://api.test', '//evil/')).toThrow()
  })
})

describe('verdicts', () => {
  const r = (status: number, json: unknown) => ({ status, ms: 1, text: JSON.stringify(json), json })
  it('judges each step by status and content', () => {
    expect(judge('list', r(200, { items: [1, 2] })).ok).toBe(true)
    expect(judge('list', r(200, { nope: 1 })).ok).toBe(false)
    expect(judge('list', r(500, {})).summary).toContain('500')
    expect(judge('create', r(201, { id: 5 })).ok).toBe(true)
    expect(judge('create', r(422, {})).ok).toBe(false)
    expect(judge('read', r(200, { id: '5' }), '5').ok).toBe(true)
    expect(judge('read', r(200, { id: '6' }), '5').ok).toBe(false)
    expect(judge('update', r(200, {})).ok).toBe(true)
    expect(judge('update', r(404, {})).ok).toBe(false)
  })
  it('summarises acceptance', () => {
    expect(acceptance({}).accepted).toBe(false)
    const pass = { verdict: 'pass' as const, summary: '' }
    const all = { preview: pass, endpoints: pass, list: pass, create: pass, read: pass, update: pass }
    expect(acceptance(all).accepted).toBe(true)
    const bad = acceptance({ ...all, update: { verdict: 'fail', summary: '' } })
    expect(bad).toMatchObject({ accepted: false, failed: 1, done: true })
  })
  it('keeps the server message for refused previews', () => {
    expect(previewRefusal('email_not_verified', 'confirm your e-mail address first')).toContain('confirm your e-mail address first')
    expect(previewRefusal('x', 'plain')).toBe('plain')
  })
})
