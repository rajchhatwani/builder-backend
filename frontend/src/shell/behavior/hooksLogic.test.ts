import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { HookBody } from '../../api/types'
import {
  CEILINGS, autoModels, blankHook, buildPoint, defaultPolicy, hookClientErrors, hookFromBody, hookIssues, hookToBody,
  legalKinds, legalPolicies, parsePoint, pointOptions, renameHook, retarget, setInputFromEntity, setOutputFromEntity,
  settableFields, stubReady, stubText, type HookCatalog,
} from './hooksLogic'

const FIXTURE = resolve(__dirname, '../../../../tests/fixtures/specs/hooks_invoice.json')
const GOLDEN = resolve(__dirname, '../../../../tests/golden/hooks_invoice/app/custom/hooks') + '/'
const fixtureHooks: HookBody[] = JSON.parse(readFileSync(FIXTURE, 'utf8')).hooks

const catalog: HookCatalog = {
  Invoice: {
    fields: [
      { name: 'id', type: 'uuid' }, { name: 'invoice_no', type: 'string' }, { name: 'amount', type: 'decimal' },
      { name: 'status', type: 'string' },
    ],
    stateField: 'status',
    transitions: ['submit', 'approve'], // manual ones only (the page filters out auto transitions)
  },
  Note: { fields: [{ name: 'id', type: 'uuid' }, { name: 'title', type: 'string' }], stateField: null, transitions: [] },
}

describe('declared hook <-> API body', () => {
  it('round-trips the fixture hooks unchanged (explicit policy only where the API sent null)', () => {
    for (const h of fixtureHooks) {
      const back = hookToBody(hookFromBody(h))
      expect(back.name).toBe(h.name)
      expect(back.point).toBe(h.point)
      expect(back.input).toEqual(h.input)
      expect(back.output).toEqual(h.output)
      expect(back.budget).toEqual(h.budget)
      expect(back.reads).toEqual(h.reads)
      expect(back.failure_policy).toBe(h.failure_policy ?? defaultPolicy(parsePoint(h.point)!.stage, h.kind!))
    }
  })
  it('turns fallback text into typed values and drops them for other policies', () => {
    const row = hookFromBody({
      name: 'x', point: 'Note.after_commit', kind: 'effect', failure_policy: 'fallback',
      input: { name: 'XInput', fields: [{ name: 'id', type: 'uuid', required: true }] },
      output: { name: 'XResult', fields: [{ name: 'sent', type: 'bool' }, { name: 'n', type: 'int' }, { name: 'r', type: 'float' }, { name: 's', type: 'string' }] },
      fallback: { sent: false, n: 3, r: 1.5, s: 'ok' },
    })
    expect(row.fallback).toEqual({ sent: 'false', n: '3', r: '1.5', s: 'ok' })
    expect(hookToBody(row).fallback).toEqual({ sent: false, n: 3, r: 1.5, s: 'ok' })
    expect(hookToBody({ ...row, policy: 'fail_open' }).fallback).toBeNull()
    // text that is not a number stays text so the backend can say why
    expect(hookToBody({ ...row, fallback: { ...row.fallback, n: 'abc' } }).fallback).toMatchObject({ n: 'abc' })
  })
  it('keeps a blank budget out of the body and blocks the save', () => {
    const row = { ...hookFromBody(fixtureHooks[0]), cpu_ms: '2x' }
    expect(hookClientErrors([row])).toEqual({ '0.cpu_ms': 'Enter a whole number' })
  })
})

describe('point picker', () => {
  it('offers the four stages per entity and a guard only for manual transitions', () => {
    const values = pointOptions(catalog).map((o) => o.value)
    expect(values).toContain('Invoice.before_save')
    expect(values).toContain('Invoice.transition_guard(submit)')
    expect(values).toContain('Invoice.transition_guard(approve)')
    expect(values).not.toContain('Invoice.transition_guard(auto_approve)')
    expect(values).not.toContain('Note.transition_guard(submit)')
    expect(values.filter((v) => v.startsWith('Note.'))).toHaveLength(4)
  })
  it('every offered point parses and round-trips', () => {
    for (const o of pointOptions(catalog)) {
      const p = parsePoint(o.value)!
      expect(buildPoint(p.entity, p.stage, p.transition)).toBe(o.value)
    }
    expect(parsePoint('invoice.before_save')).toBeNull()
    expect(parsePoint('Invoice.transition_guard()')).toBeNull()
  })
  it('a project without entities has no points', () => {
    expect(pointOptions({})).toEqual([])
  })
})

describe('legal combinations (mirror of validation_hooks.py)', () => {
  it('effect only after commit', () => {
    expect(legalKinds('after_commit')).toEqual(['pure', 'effect'])
    for (const s of ['before_save', 'validate', 'after_save', 'transition_guard'] as const) expect(legalKinds(s)).toEqual(['pure'])
  })
  it('guards and validation fail closed; after_commit cannot', () => {
    expect(legalPolicies('transition_guard')).toEqual(['fail_closed'])
    expect(legalPolicies('validate')).toEqual(['fail_closed'])
    expect(legalPolicies('after_commit')).toEqual(['fail_open', 'fallback'])
    expect(legalPolicies('before_save')).toEqual(['fail_closed', 'fail_open', 'fallback'])
  })
  it('moving to another point repairs kind, policy, budget, inputs and output', () => {
    const effect = hookFromBody(fixtureHooks[1]) // Invoice.after_commit, effect, rows 20, reads Invoice
    const toGuard = retarget(effect, 'Invoice.transition_guard(submit)', catalog)
    expect(toGuard.kind).toBe('pure')
    expect(toGuard.policy).toBe('fail_closed')
    expect(toGuard.rows).toBe('0')
    expect(toGuard.reads).toEqual([])
    expect(toGuard.outputFields.map((f) => f.name)).toEqual(['allowed', 'reason'])
    expect(toGuard.inputFields.map((f) => f.name)).toEqual(['id', 'invoice_no', 'status', 'amount'])
    const toNote = retarget(effect, 'Note.after_commit', catalog)
    expect(toNote.inputFields.map((f) => f.name)).toEqual(['id']) // invoice-only fields dropped
    expect(retarget({ ...effect, cpu_ms: '999999' }, effect.point, catalog).cpu_ms).toBe(String(CEILINGS.effect.cpu_ms))
  })
  it('a pure hook cannot keep reads or rows when switched from effect', () => {
    const effect = hookFromBody(fixtureHooks[1])
    const pure = retarget({ ...effect, kind: 'pure' }, effect.point, catalog)
    expect(pure.reads).toEqual([])
    expect(pure.rows).toBe('0')
  })
  it('a new hook starts legal at the first point', () => {
    const row = blankHook(catalog)
    expect(row.point).toBe('Invoice.before_save')
    expect(legalPolicies('before_save')).toContain(row.policy)
    expect(row.inputFields.map((f) => f.name)).toEqual(['id'])
  })
})

describe('field pickers', () => {
  it('before_save may set neither id nor the state field', () => {
    expect(settableFields(catalog.Invoice).map((f) => f.name)).toEqual(['invoice_no', 'amount'])
  })
  it('toggling takes the type from the entity', () => {
    let row = blankHook(catalog)
    row = setOutputFromEntity(row, catalog.Invoice, 'amount', true)
    expect(row.outputFields).toEqual([{ name: 'amount', type: 'decimal', required: true }])
    row = setInputFromEntity(row, catalog.Invoice, 'invoice_no', true)
    expect(row.inputFields.map((f) => f.name)).toEqual(['id', 'invoice_no'])
    row = setInputFromEntity(row, catalog.Invoice, 'id', false)
    expect(row.inputFields.map((f) => f.name)).toEqual(['invoice_no'])
  })
})

describe('model names', () => {
  it('derives names from the hook name until the user picks their own', () => {
    expect(autoModels('match_invoice')).toEqual({ input: 'MatchInvoiceInput', output: 'MatchInvoiceResult' })
    expect(autoModels('Bad Name')).toEqual({ input: '', output: '' })
    let row = renameHook(blankHook(catalog), 'check_po')
    expect(row.inputModel).toBe('CheckPoInput')
    row = renameHook({ ...row, inputModel: 'MyIn' }, 'check_po2')
    expect(row.inputModel).toBe('MyIn')
    expect(row.outputModel).toBe('CheckPo2Result')
  })
})

describe('stub text (format of stub_source in the hooks generator block)', () => {
  it.each(['match_invoice', 'notify_approved'])('matches the generator golden byte for byte: %s', (name) => {
    const hook = fixtureHooks.find((h) => h.name === name)!
    // The golden uses its own model names; compare using them (same fixture, same names).
    expect(stubText(hook)).toBe(readFileSync(`${GOLDEN}${name}.py`, 'utf8'))
  })
  it('has the fixed signature line and one marked body region', () => {
    const text = stubText(fixtureHooks[0])
    const lines = text.split('\n')
    expect(lines).toContain('def match_invoice(data: MatchInput) -> MatchResult:  # platform:signature (fixed)')
    expect(lines.filter((l) => l.includes('<agent:body hook=match_invoice>'))).toHaveLength(1)
    expect(lines.filter((l) => l.includes('</agent:body>'))).toHaveLength(1)
  })
  it('is only shown when the generator would accept the names', () => {
    const ok = hookFromBody(fixtureHooks[0])
    expect(stubReady(ok)).toBe(true)
    expect(stubReady({ ...ok, name: 'Bad Name' })).toBe(false)
    expect(stubReady({ ...ok, inputModel: '' })).toBe(false)
    expect(stubReady({ ...ok, point: 'nonsense' })).toBe(false)
  })
})

describe('issue path -> form field', () => {
  const issue = (path: string, message = 'm') => ({ path, code: 'invalid_value', message })
  it('maps hook issues to the control they belong to', () => {
    const r = hookIssues([
      issue('hooks[0].name', 'a'),
      issue('hooks[0].point', 'b'),
      issue('hooks[0].kind', 'c'),
      issue('hooks[0].failure_policy', 'd'),
      issue('hooks[0].budget.cpu_ms', 'e'),
      issue('hooks[1].input.name', 'f'),
      issue('hooks[1].output.fields[2].name', 'g'),
      issue('hooks[1].input.fields[0].type', 'h'),
      issue('hooks[1].fallback.sent', 'i'),
      issue('hooks[1].reads[0]', 'j'),
      issue('hooks', 'too many'),
      issue('settings[0].key', 'not ours'),
    ])
    expect(r.section).toEqual(['too many'])
    expect(r.rows[0].fields).toEqual({ name: ['a'], point: ['b'], kind: ['c'], failure_policy: ['d'], cpu_ms: ['e'] })
    expect(r.rows[1].fields).toEqual({ inputModel: ['f'], outputFields: ['g'], inputFields: ['h'], fallback: ['i'], reads: ['j'] })
  })
})

describe('stub text hardening', () => {
  it('refuses an illegal kind instead of writing it into the header', () => {
    const hook = { ...fixtureHooks[0], kind: 'x\nimport os' } as typeof fixtureHooks[0]
    expect(stubText(hook)).toBe('')
    expect(stubReady({ ...hookFromBody(fixtureHooks[0]), kind: 'x\nimport os' })).toBe(false)
    expect(stubText({ ...fixtureHooks[0], kind: 'effect' })).toContain('kind=effect')
  })
})
