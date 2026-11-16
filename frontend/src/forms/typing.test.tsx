import { act, createElement, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { SchemaForm } from './SchemaForm'
import { csvToList, listToCsv } from './schemaLogic'
import { shownText } from './useRawText'
import { parseLiteral, literalToText } from '../components/authz/policyModel'
import { columnsToText, rowsToText, textToColumns, textToRows } from '../components/documents/blocks'
import { ParsedTextarea } from '../components/ParsedTextarea'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** Types char by char the way the controlled input would: the shown text is what the next key is appended to. */
function typeInto<T>(keys: string, parse: (t: string) => T, toText: (v: T) => string): string {
  let raw = ''
  let value = parse('')
  for (const c of keys) {
    raw = shownText(raw, value, parse, toText) + c
    value = parse(raw)
  }
  return shownText(raw, value, parse, toText)
}

describe('typing keeps separators (F-0561..F-0563, F-0568)', () => {
  it('csv list', () => expect(typeInto('a, b', csvToList, listToCsv)).toBe('a, b'))
  it('rows text', () => {
    expect(typeInto('Total :: 5\nTax', textToRows, rowsToText)).toBe('Total :: 5\nTax')
  })
  it('columns text', () => expect(typeInto('Item :: {{x}} :: right :: 2', textToColumns, columnsToText)).toBe('Item :: {{x}} :: right :: 2'))
  it('literal with spaces, lists and decimals', () => {
    const p = (list: boolean, kind?: string) => (t: string) => parseLiteral(t, list, kind)
    expect(typeInto('in progress', p(false), literalToText)).toBe('in progress')
    expect(typeInto('10.0.0.0/8, 192.168.0.0/16', p(true), literalToText)).toBe('10.0.0.0/8, 192.168.0.0/16')
    expect(typeInto('0.5', p(false, 'number'), literalToText)).toBe('0.5')
  })
  it('resyncs when the parent value changes elsewhere', () => {
    expect(shownText('a,', ['x', 'y'], csvToList, listToCsv)).toBe('x, y')
  })
  it('parsing needs numbers for integer literals', () => {
    expect(parseLiteral('8', false, 'integer')).toBe(8)
  })
})

let root: Root | null = null
let host: HTMLElement
afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
})

function setText(el: HTMLInputElement | HTMLTextAreaElement, text: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, text)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('real inputs', () => {
  it('csv widget accepts a typed second entry', () => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    let latest: unknown
    const schema = { type: 'array', items: { type: 'string' }, 'x-ui': { widget: 'csv' } } as never
    function H() {
      const [v, s] = useState<unknown>([])
      latest = v
      return createElement(SchemaForm, { schema, value: v, onChange: (n: unknown) => s(n), idPrefix: 't' })
    }
    act(() => root!.render(createElement(H)))
    const input = host.querySelector('input')!
    for (const t of ['a', 'a,', 'a, ', 'a, b']) act(() => setText(input, t))
    expect(input.value).toBe('a, b')
    expect(latest).toEqual(['a', 'b'])
  })

  it('block textarea keeps text while typing', () => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    function H() {
      const [rows, s] = useState<{ label: string; value: string }[]>([])
      return createElement(ParsedTextarea<{ label: string; value: string }[]>, { rows: 3, value: rows, parse: textToRows, toText: rowsToText, onChange: s })
    }
    act(() => root!.render(createElement(H)))
    const ta = host.querySelector('textarea')!
    for (const t of ['T', 'To', 'Total ', 'Total :: ', 'Total :: 5', 'Total :: 5\n']) act(() => setText(ta, t))
    expect(ta.value).toBe('Total :: 5\n')
  })
})
