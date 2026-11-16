import { act, createElement, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { SchemaForm } from './SchemaForm'
import { csvToList, listToCsv } from './schemaLogic'
import { shownText } from './useRawText'
import { parseLiteral } from '../components/authz/policyModel'
import { UiProvider } from '../components/Ui'
import { BlockEditor } from '../components/documents/BlockEditor'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('helpers (F-0561..F-0563)', () => {
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

/** One keystroke: appends the char to whatever the input currently shows. */
function key(el: HTMLInputElement | HTMLTextAreaElement, c: string) {
  act(() => setText(el, el.value + c))
}
const typeKeys = (el: HTMLInputElement | HTMLTextAreaElement, keys: string) => {
  for (const c of keys) key(el, c)
}

describe('real inputs, one keystroke at a time', () => {
  it('csv widget accepts a typed second entry (F-0561)', () => {
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
    typeKeys(input, 'a, b')
    expect(input.value).toBe('a, b')
    expect(latest).toEqual(['a', 'b'])
  })

  it('BlockEditor rows and columns textareas keep text while typing (F-0562)', () => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    let latest: Record<string, unknown>[] = []
    function H() {
      const [b, s] = useState<Record<string, unknown>[]>([{ type: 'kv', rows: [] }, { type: 'table', source: 'items', columns: [] }])
      latest = b
      return createElement(UiProvider, null, createElement(BlockEditor, { blocks: b as never, onChange: (n) => s(n as unknown as Record<string, unknown>[]) }) as never)
    }
    act(() => root!.render(createElement(H)))
    const [kv, table] = Array.from(host.querySelectorAll('textarea'))
    typeKeys(kv, 'Total :: 5\nTax')
    expect(kv.value).toBe('Total :: 5\nTax')
    expect(latest[0].rows).toEqual([{ label: 'Total', value: '5' }, { label: 'Tax', value: '' }])
    typeKeys(table, 'Item :: {{x}} :: right')
    expect(table.value).toBe('Item :: {{x}} :: right')
  })
})
