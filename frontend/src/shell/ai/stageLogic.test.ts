import { describe, expect, it } from 'vitest'
import { MAX_LOG_LINES, backoffDelay, buildTree, createSseParser, discoverEntities, extractRows, languageFor, pageQuery, pushLines, describeSaveError, type LogLine } from './stageLogic'

const line = (i: number): LogLine => ({ id: i, kind: 'log', text: `l${i}` })

describe('stage logic', () => {
  it('detects languages by extension', () => {
    expect(languageFor('app/x.py')).toBe('python')
    expect(languageFor('a/b.JSON')).toBe('json')
    expect(languageFor('c.yml')).toBe('yaml')
    expect(languageFor('Makefile')).toBe('plaintext')
  })
  it('builds a sorted tree with folders first', () => {
    const f = (path: string) => ({ path, zone: 'custom', size: 1, editable: true })
    const t = buildTree([f('b.py'), f('hooks/a.py'), f('a.py')])
    expect(t.map((n) => n.name)).toEqual(['hooks', 'a.py', 'b.py'])
    expect(t[0].children[0].file?.path).toBe('hooks/a.py')
  })
  it('bounds the log buffer to the newest 2000 lines', () => {
    let buf: LogLine[] = []
    for (let i = 0; i < 3; i++) buf = pushLines(buf, Array.from({ length: 900 }, (_, k) => line(i * 900 + k)))
    expect(buf).toHaveLength(MAX_LOG_LINES)
    expect(buf[buf.length - 1].id).toBe(2699)
    expect(buf[0].id).toBe(700)
  })
  it('parses SSE across chunk boundaries', () => {
    const p = createSseParser()
    expect(p('data: hel')).toEqual([])
    expect(p('lo\r\n\r\nevent: state\ndata: sleeping\n\n')).toEqual([{ event: 'message', data: 'hello' }, { event: 'state', data: 'sleeping' }])
  })
  it('backs off with a cap', () => {
    expect(backoffDelay(0)).toBe(1000)
    expect(backoffDelay(99)).toBe(15000)
  })
  it('discovers list endpoints only', () => {
    const doc = { paths: { '/invoices': { get: { responses: {} }, post: {} }, '/invoices/{id}': { get: {} }, '/openapi.json': { get: {} }, '/health': { get: {} } } }
    expect(discoverEntities(doc).map((e) => e.name)).toEqual(['invoices'])
  })
  it('extracts rows and columns from arrays and envelopes', () => {
    expect(extractRows([{ a: 1 }, { b: 2 }])?.columns).toEqual(['a', 'b'])
    expect(extractRows({ items: [{ a: 1 }], total: 40 })).toMatchObject({ total: 40, columns: ['a'] })
    expect(extractRows({ nope: 1 })).toBeNull()
  })
  it('pages with limit/offset', () => { expect(pageQuery(2)).toBe('limit=25&offset=50') })
  it('explains save errors', () => {
    expect(describeSaveError(403, 'file_not_editable')).toMatch(/spec/)
    expect(describeSaveError(409, 'file_changed')).toMatch(/changed/)
    expect(describeSaveError(409, 'workspace_busy')).toMatch(/busy/)
  })
})
