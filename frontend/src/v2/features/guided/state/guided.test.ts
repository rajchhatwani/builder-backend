import { describe, expect, it } from 'vitest'
import { emptyDraft, intakeReducer } from './intake'
import { buildScope, extensionRows, planReducer, scopeRows } from './plan'

describe('intake draft', () => {
  it('keeps the prompt and applies the document limit across separate selections', () => {
    const entered = intakeReducer(emptyDraft, { type: 'prompt', value: 'Request' })
    const files = Array.from({ length: 6 }, (_, index) => new File(['request'], `brief-${index}.md`))
    const picked = intakeReducer(entered, { type: 'pick', files: files.slice(0, 4) })
    const overflow = intakeReducer(picked, { type: 'pick', files: files.slice(4) })
    expect(overflow.prompt).toBe('Request')
    expect(overflow.files).toEqual(files.slice(0, 5))
    expect(overflow.fileErrors[0].key).toBe('validation.documentCount')
    expect(intakeReducer(overflow, { type: 'remove', index: 0 }).files).toEqual(files.slice(1, 5))
    expect(intakeReducer(overflow, { type: 'clear' })).toEqual(emptyDraft)
  })
})

describe('plan scope', () => {
  it('keeps changes reversible and emits the canonical scope per category', () => {
    const rows = scopeRows({ entities: ['TimeOff', 'Employee'], hooks: ['audit'] })
    const removed = planReducer(rows, { type: 'toggle', row: rows[0] })
    const added = planReducer(removed, { type: 'add', row: { kind: 'entities', name: 'Department' } })
    expect(buildScope(added)).toEqual({ entities: ['Department', 'Employee'], hooks: ['audit'] })
    expect(buildScope(planReducer(added, { type: 'toggle', row: rows[0] }))).toEqual({
      entities: ['Department', 'Employee', 'TimeOff'], hooks: ['audit'],
    })
  })

  it('reads scope extensions without interpreting them as a replacement plan', () => {
    expect(extensionRows({ extend_items: [{ kind: 'hook', name: 'audit' }] })).toEqual([{ kind: 'hooks', name: 'audit' }])
    expect(extensionRows({ plan: { entities: ['Employee'] } })).toBeUndefined()
  })
})
