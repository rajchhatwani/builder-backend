import { createElement, useState } from 'react'
import { describe, expect, it } from 'vitest'
import { mount, setInput } from '../../shell/ai/testUtils'
import { ConditionEditor } from './ConditionEditor'
import type { Catalogue } from './policyModel'
import type { PolicyCondition } from '../../api/types'

const catalogue: Catalogue = { resource: { Post: { status: 'string' } }, subject: { id: 'uuid', level: 'integer', roles: 'list' }, roles: [], entities: [{ name: 'Post', ops: ['get'] }] }

async function render(initial: PolicyCondition) {
  let latest: PolicyCondition | null = initial
  function H() {
    const [v, s] = useState<PolicyCondition | null>(initial)
    latest = v
    return createElement(ConditionEditor, { value: v, onChange: s, catalogue, entities: ['Post'] })
  }
  const host = await mount(createElement(H))
  return { host, get: () => latest as { all: { left: unknown; op: string; right: unknown }[] } }
}

describe('ConditionEditor', () => {
  it('numbers typed against a moment attribute are stored as numbers (F-0564)', async () => {
    const r = await render({ all: [{ left: { env: 'hour_utc' }, op: 'gte', right: { literal: '' } }] })
    await setInput(r.host.querySelector('input[aria-label="Value"]') as HTMLInputElement, '8')
    expect(r.get().all[0].right).toEqual({ literal: 8 })
  })
  it('numbers typed against a person attribute are stored as numbers (F-0564)', async () => {
    const r = await render({ all: [{ left: { subject: 'level' }, op: 'gte', right: { literal: '' } }] })
    await setInput(r.host.querySelector('input[aria-label="Value"]') as HTMLInputElement, '3')
    expect(r.get().all[0].right).toEqual({ literal: 3 })
  })
  it('changing the comparison reshapes the literal (F-0565)', async () => {
    const r = await render({ all: [{ left: { resource: 'status' }, op: 'in', right: { literal: ['a', 'b'] } }] })
    await setInput(r.host.querySelector('select[aria-label="Comparison"]') as HTMLSelectElement, 'eq')
    expect(r.get().all[0].right).toEqual({ literal: 'a, b' })
    await setInput(r.host.querySelector('select[aria-label="Comparison"]') as HTMLSelectElement, 'in')
    expect(r.get().all[0].right).toEqual({ literal: ['a', 'b'] })
  })
  it('a typed list keeps its commas (F-0563)', async () => {
    const r = await render({ all: [{ left: { resource: 'status' }, op: 'in', right: { literal: [] } }] })
    const input = () => r.host.querySelector('input[aria-label="Value"]') as HTMLInputElement
    for (const t of ['a', 'a,', 'a, ', 'a, b']) await setInput(input(), t)
    expect(input().value).toBe('a, b')
    expect(r.get().all[0].right).toEqual({ literal: ['a', 'b'] })
  })
})
