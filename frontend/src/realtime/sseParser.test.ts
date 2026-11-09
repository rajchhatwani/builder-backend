import { describe, expect, it } from 'vitest'
import { createSseParser } from './sseParser'

describe('sse parser', () => {
  it('parses id/event/data frames and skips comments', () => {
    const p = createSseParser()
    expect(p.push(': open\n\nid: 5\nevent: spec.changed\ndata: {"a":1}\n\n')).toEqual([{ id: '5', event: 'spec.changed', data: '{"a":1}' }])
  })
  it('is safe at every split point', () => {
    const text = ': hi\n\nid: 1\nevent: a\ndata: x\ndata: y\n\nid: 2\r\nevent: b\r\ndata: z\r\n\r\n'
    const whole = createSseParser().push(text)
    expect(whole).toEqual([{ id: '1', event: 'a', data: 'x\ny' }, { id: '2', event: 'b', data: 'z' }])
    for (let i = 0; i <= text.length; i++) {
      const p = createSseParser()
      expect([...p.push(text.slice(0, i)), ...p.push(text.slice(i))]).toEqual(whole)
    }
    const p = createSseParser()
    expect([...text].flatMap((c) => p.push(c))).toEqual(whole)
  })
  it('handles bare CR, BOM, default event and ignores id with NUL and bad retry', () => {
    const p = createSseParser()
    expect(p.push('﻿data: hi\r\r')).toEqual([{ event: 'message', data: 'hi' }])
    expect(p.push('id: a\0b\nretry: x\ndata: 1\n\n')).toEqual([{ event: 'message', data: '1' }])
    expect(p.push('retry: 3000\ndata:\n\n')).toEqual([{ event: 'message', data: '', retry: 3000 }])
  })
  it('does not emit a frame without data and drops an unfinished tail', () => {
    const p = createSseParser()
    expect(p.push('event: x\n\n')).toEqual([])
    expect(p.push('data: partial')).toEqual([])
  })
})
