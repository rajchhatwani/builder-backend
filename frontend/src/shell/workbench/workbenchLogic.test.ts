import { describe, expect, it } from 'vitest'
import {
  buildRequestUrl, formatResponseText, generatePayload, parseOperations, pushHistory, redactBodyText,
  redactJson, resolvePreviewOrigin, MAX_HISTORY, MAX_RESPONSE_CHARS, type HistoryEntry,
} from './workbenchLogic'

const doc = {
  paths: {
    '/invoices': {
      get: { summary: 'List', parameters: [{ name: 'limit', in: 'query', schema: { type: 'integer' } }] },
      post: { summary: 'Create', requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/InvoiceIn' } } } } },
    },
    '/invoices/{id}': {
      parameters: [{ name: 'id', in: 'path', required: true, schema: { type: 'string' } }],
      delete: {},
      options: {},
    },
    '//evil.example/x': { get: {} },
    '/a/../b': { get: {} },
  },
  components: {
    schemas: {
      InvoiceIn: {
        type: 'object',
        required: ['number', 'amount', 'status', 'email'],
        properties: {
          number: { type: 'string', minLength: 3 },
          amount: { type: 'number', minimum: 5 },
          status: { enum: ['draft', 'sent'] },
          email: { type: 'string', format: 'email' },
          note: { type: 'string' },
          self: { $ref: '#/components/schemas/InvoiceIn' },
        },
      },
    },
  },
}

describe('resolvePreviewOrigin', () => {
  it('accepts http(s) and keeps only the origin', () => {
    expect(resolvePreviewOrigin('http://localhost:8799/some/path?x=1#h')).toBe('http://localhost:8799')
    expect(resolvePreviewOrigin('https://preview.example.com')).toBe('https://preview.example.com')
  })
  it('refuses unset, other schemes, credentials, garbage and the builder origin', () => {
    expect(resolvePreviewOrigin(undefined)).toBeNull()
    expect(resolvePreviewOrigin('')).toBeNull()
    expect(resolvePreviewOrigin('javascript:alert(1)')).toBeNull()
    expect(resolvePreviewOrigin('file:///etc/passwd')).toBeNull()
    expect(resolvePreviewOrigin('http://user:pw@host')).toBeNull()
    expect(resolvePreviewOrigin('not a url')).toBeNull()
    expect(resolvePreviewOrigin('http://localhost:8000/x', ['http://localhost:8000'])).toBeNull()
  })
})

describe('parseOperations', () => {
  const ops = parseOperations(doc)
  it('lists allowed methods only and drops hostile paths', () => {
    expect(ops.map((o) => o.id)).toEqual(['GET /invoices', 'POST /invoices', 'DELETE /invoices/{id}'])
  })
  it('merges path-level parameters and finds the JSON body schema', () => {
    expect(ops[2].params.map((p) => p.name)).toEqual(['id'])
    expect(ops[1].bodySchema).not.toBeNull()
    expect(ops[0].bodySchema).toBeNull()
  })
  it('is safe on junk', () => {
    expect(parseOperations(null)).toEqual([])
    expect(parseOperations({ paths: 3 })).toEqual([])
  })
})

describe('buildRequestUrl', () => {
  const ops = parseOperations(doc)
  const origin = 'http://localhost:8799'
  it('encodes path params and adds query', () => {
    expect(buildRequestUrl(origin, '/invoices/{id}', { id: 'a/b c' }, ops[2].params)).toBe('http://localhost:8799/invoices/a%2Fb%20c')
    expect(buildRequestUrl(origin, '/invoices', { limit: '5' }, ops[0].params)).toBe('http://localhost:8799/invoices?limit=5')
  })
  it('refuses a missing param and any path that could leave the origin', () => {
    expect(() => buildRequestUrl(origin, '/invoices/{id}', {}, ops[2].params)).toThrow(/required/)
    expect(() => buildRequestUrl(origin, '//evil.example/x', {}, [])).toThrow()
    expect(() => buildRequestUrl(origin, 'http://evil.example/', {}, [])).toThrow()
    expect(() => buildRequestUrl(origin, '/\\evil.example', {}, [])).toThrow()
    expect(() => buildRequestUrl(origin, '/x/{unknown}', {}, [])).toThrow(/not filled/)
  })
})

describe('generatePayload', () => {
  const schema = (doc.components.schemas as Record<string, unknown>).InvoiceIn
  it('valid: required fields only, honouring constraints, cycle safe', () => {
    expect(generatePayload(doc, schema, 'valid')).toEqual({ number: 'aaa', amount: 5, status: 'draft', email: 'user@example.com' })
  })
  it('resolves $ref and invalid mode breaks one rule', () => {
    const ref = { $ref: '#/components/schemas/InvoiceIn' }
    const bad = generatePayload(doc, ref, 'invalid') as Record<string, unknown>
    expect(bad).not.toHaveProperty('number')
    expect(Object.keys(bad)).toHaveLength(3)
  })
  it('ignores remote and prototype refs', () => {
    expect(generatePayload(doc, { $ref: 'http://evil/x' }, 'valid')).toBeNull()
    expect(generatePayload(doc, { $ref: '#/__proto__/x' }, 'valid')).toBeNull()
  })
  it('self-referencing required property terminates', () => {
    const cyc = { components: { schemas: { N: { type: 'object', required: ['n'], properties: { n: { $ref: '#/components/schemas/N' } } } } } }
    expect(() => generatePayload(cyc, { $ref: '#/components/schemas/N' }, 'valid')).not.toThrow()
  })
})

describe('redaction and history', () => {
  it('redacts secret-looking keys deeply', () => {
    expect(redactJson({ a: 1, access_token: 'x', n: { Password: 'p', list: [{ api_key: 'k', ok: 2 }] } })).toEqual({
      a: 1, access_token: '[redacted]', n: { Password: '[redacted]', list: [{ api_key: '[redacted]', ok: 2 }] },
    })
  })
  it('redacts bearer values in non-JSON text and never keeps a token', () => {
    expect(redactBodyText('oops Bearer abc.def.ghi failed')).toBe('oops Bearer [redacted] failed')
    expect(redactBodyText('{"token":"zzz","x":1}')).not.toContain('zzz')
  })
  it('caps history, newest first', () => {
    let list: HistoryEntry[] = []
    for (let i = 0; i < MAX_HISTORY + 5; i++) {
      list = pushHistory(list, { id: i, at: '', method: 'GET', path: '/', role: 'a', status: 200, ms: 1, authorization: 'none', requestBody: '', responseBody: '', error: '' })
    }
    expect(list).toHaveLength(MAX_HISTORY)
    expect(list[0].id).toBe(MAX_HISTORY + 4)
  })
  it('formats JSON and caps long text', () => {
    expect(formatResponseText('{"a":1}')).toBe('{\n  "a": 1\n}')
    expect(formatResponseText('x'.repeat(MAX_RESPONSE_CHARS + 10))).toMatch(/truncated$/)
    expect(formatResponseText('<img src=x onerror=alert(1)>')).toBe('<img src=x onerror=alert(1)>')
  })
})

import { redactBodyText as rbt, redactJson as rj, redactPath as rpath } from './workbenchLogic'
describe('wider redaction', () => {
  it('redacts jwt, bearer, otp, pin, auth, accessKey and bare key names, keeps ordinary ones', () => {
    const out = rj({ jwt: 'a', bearer: 'b', otp: 'c', pin: 'd', auth: 'e', accessKey: 'f', key: 'g', name: 'ok', amount: 5 }) as Record<string, unknown>
    for (const k of ['jwt', 'bearer', 'otp', 'pin', 'auth', 'accessKey', 'key']) expect(out[k]).toBe('[redacted]')
    expect(out.name).toBe('ok')
    expect(out.amount).toBe(5)
  })
  it('redacts secret-looking query parameters and JWT-looking values in the path', () => {
    const p = rpath('/orders?page=2&access_token=abc123&x=eyJhbGciOi.eyJzdWIiOi.sig')
    expect(p).toContain('page=2')
    expect(p).not.toContain('abc123')
    expect(p).not.toContain('eyJhbGciOi')
    expect(rpath('/plain')).toBe('/plain')
  })
  it('redacts tokens in non-JSON bodies', () => {
    const t = rbt('token=abc123&name=bob Authorization: Bearer zzz.yyy eyJhbGciOi.eyJzdWIiOi.sig')
    expect(t).not.toMatch(/abc123|zzz\.yyy|eyJhbGciOi/)
    expect(t).toContain('name=bob')
  })
})
