import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { SeedProfileBody, ValidationIssue } from '../../api/types'
import {
  columnTypes, generatorsFor, genFromBody, genToBody, missingRequired, normalizeKey, plannableColumns, profileFromBody,
  profileToBody, reachableStates, retypeGen, runCommands, seedClientErrors, seedIssues, suggestGen, targetOf, withStateWeights,
  type SeedCatalog, type SeedColumn,
} from './seedLogic'

const FIXTURE = resolve(__dirname, '../../../../tests/fixtures/specs/seed_demo.json')
const spec = JSON.parse(readFileSync(FIXTURE, 'utf8'))
const fixtureSeed: SeedProfileBody[] = spec.seed

const col = (name: string, type: string, extra: Partial<SeedColumn> = {}): SeedColumn => ({
  name, type, required: false, unique: false, hasDefault: false, maxLength: null, minValue: null, maxValue: null, enumValues: [], ...extra,
})
const STATES = ['draft', 'submitted', 'approved', 'paid', 'rejected']
const catalog: SeedCatalog = {
  Customer: {
    columns: [col('name', 'string', { required: true, maxLength: 80 }), col('email', 'string', { required: true, unique: true, maxLength: 120 }), col('notes', 'text'), col('active', 'boolean', { hasDefault: true })],
    fks: [], stateField: null, reachable: [],
  },
  Invoice: {
    columns: [
      col('invoice_no', 'string', { required: true, unique: true, maxLength: 40 }), col('amount', 'decimal', { required: true, minValue: 0 }),
      col('issued_on', 'date', { required: true }), col('memo', 'string', { maxLength: 200 }), col('status', 'enum', { required: true, enumValues: STATES }),
      col('api_token', 'string'), col('blob', 'uuid'),
    ],
    fks: [{ column: 'customer_id', target: 'Customer', required: true, unique: false }],
    stateField: 'status', reachable: STATES,
  },
}
const types = columnTypes(catalog)
const target = (e: string, f: string) => targetOf(catalog[e], f)!

describe('seed profile <-> API body', () => {
  it('round-trips the seed_demo fixture profiles unchanged', () => {
    for (const p of fixtureSeed) expect(profileToBody(profileFromBody(p), types)).toEqual(p)
  })
  it('turns text boxes into typed values and sends only the keys of the generator type', () => {
    expect(genToBody({ ...suggestGen(target('Customer', 'name'), { asOfYear: 2026 }), type: 'words', min_words: '2', max_words: '3', prefix: 'ignored' }, 'string'))
      .toEqual({ type: 'words', min_words: 2, max_words: 3 })
    expect(genToBody(genFromBody({ type: 'one_of', values: [1, 2] }), 'integer')).toEqual({ type: 'one_of', values: [1, 2] })
    expect(genToBody({ ...retypeGen(target('Invoice', 'amount'), 'decimal_range', { asOfYear: 2026 }), min: '20.00', max: '900.00' }, 'decimal'))
      .toEqual({ type: 'decimal_range', min: '20.00', max: '900.00', places: 2 })
    expect(genToBody({ ...retypeGen(target('Customer', 'active'), 'constant', { asOfYear: 2026 }), value: 'true' }, 'boolean')).toEqual({ type: 'constant', value: true })
    // whole-number sequence on an integer column takes only start
    expect(genToBody({ ...retypeGen({ kind: 'field', col: col('n', 'integer'), isState: false }, 'sequence', { asOfYear: 2026 }), prefix: 'X', width: '5' }, 'integer')).toEqual({ type: 'sequence', start: 1 })
    // state weights: blanks dropped
    expect(genToBody({ ...retypeGen(target('Invoice', 'status'), 'state', { asOfYear: 2026 }), weights: { draft: '1', paid: '' } }, 'enum')).toEqual({ type: 'state', weights: { draft: 1 } })
  })
  it('keeps text that is not a number as text so the backend can explain it', () => {
    expect(genToBody({ ...retypeGen(target('Customer', 'name'), 'constant', { asOfYear: 2026 }), value: '12x' }, 'integer')).toEqual({ type: 'constant', value: '12x' })
  })
  it('uses the profile row numbers as numbers', () => {
    const body = profileToBody({ ...profileFromBody(fixtureSeed[0]), seed: '7', tenants: '3' }, types)
    expect(body.seed).toBe(7)
    expect(body.tenants).toBe(3)
  })
})

describe('generator pickers only offer possible combinations', () => {
  it('state column: only state; foreign key: only reference', () => {
    expect(generatorsFor(target('Invoice', 'status'))).toEqual(['state'])
    expect(generatorsFor(target('Invoice', 'customer_id'))).toEqual(['reference'])
  })
  it('unique column: only sequence or email; secret-looking name: no constant/one_of/words', () => {
    expect(generatorsFor(target('Customer', 'email'))).toEqual(['sequence', 'email'])
    expect(generatorsFor(target('Invoice', 'invoice_no'))).toEqual(['sequence', 'email'])
    expect(generatorsFor(target('Invoice', 'api_token'))).toEqual(['sequence', 'email'])
  })
  it('by column type', () => {
    expect(generatorsFor(target('Invoice', 'amount'))).toEqual(['constant', 'one_of', 'decimal_range'])
    expect(generatorsFor(target('Invoice', 'issued_on'))).toEqual(['constant', 'one_of', 'date_range'])
    expect(generatorsFor(target('Customer', 'active'))).toEqual(['constant', 'one_of', 'bool_ratio'])
    expect(generatorsFor(target('Customer', 'notes'))).toEqual(['constant', 'one_of', 'sequence', 'words', 'email'])
  })
  it('lists fields still to plan; types with no generator are never offered', () => {
    const plan = { k: 1, entity: 'Invoice', count: '3', fields: [{ k: 2, field: 'memo', gen: suggestGen(target('Invoice', 'memo'), { asOfYear: 2026 }) }] }
    expect(plannableColumns(catalog.Invoice, plan)).toEqual(['invoice_no', 'amount', 'issued_on', 'status', 'api_token', 'customer_id'])
    expect(missingRequired(catalog.Invoice, plan)).toEqual(['invoice_no', 'amount', 'issued_on', 'customer_id']) // state column is filled by the machine
  })
  it('suggested generators respect max_length and a unique column', () => {
    expect(suggestGen(target('Customer', 'email'), { asOfYear: 2026 })).toMatchObject({ type: 'email', prefix: 'user' })
    expect(suggestGen(target('Invoice', 'invoice_no'), { asOfYear: 2026 })).toMatchObject({ type: 'sequence', prefix: 'invoic-', start: '1' })
    expect(suggestGen({ kind: 'field', col: col('code', 'string', { maxLength: 8 }), isState: false }, { asOfYear: 2026 })).toMatchObject({ type: 'words', max_words: '1' })
    expect(suggestGen(target('Invoice', 'customer_id'), { asOfYear: 2026 })).toMatchObject({ type: 'reference', entity: 'Customer', pick: 'random' })
  })
  it('state weights start on the reachable states only', () => {
    const m = { entity: 'X', field: 's', initial: 'a', transitions: [{ name: 't', from_states: ['a'], to_state: 'b' }] }
    expect(reachableStates(m, ['a', 'b', 'c'])).toEqual(['a', 'b'])
    const info = { ...catalog.Invoice, reachable: ['draft', 'submitted'] }
    const g = withStateWeights(retypeGen(target('Invoice', 'status'), 'state', { asOfYear: 2026 }), info, STATES)
    expect(g.weights).toEqual({ draft: '1', submitted: '1' })
  })
})

describe('client checks and issue-path mapping', () => {
  it('flags only shape problems, keyed like the backend paths', () => {
    const rows = [profileFromBody(fixtureSeed[0])]
    expect(seedClientErrors(rows)).toEqual({})
    rows[0].seed = 'abc'
    rows[0].entities[1].count = '1.5'
    rows[0].entities[1].fields[1].gen.places = 'x'
    rows[0].entities[1].fields[5].gen.weights.draft = 'many'
    expect(seedClientErrors(rows)).toEqual({
      '0.seed': 'Enter a whole number',
      '0.entities.1.count': 'Enter a whole number',
      '0.entities.1.fields.1.generator.places': 'Enter a whole number',
      '0.entities.1.fields.5.generator.weights.draft': 'Enter a whole number',
    })
  })
  it('maps backend issues to profile, plan and generator controls', () => {
    const issue = (path: string, message: string): ValidationIssue => ({ path, code: 'x', message })
    const out = seedIssues([
      issue('seed', 'at most 5 seed profiles'),
      issue('seed[0].tenants', 'tenants must be 0 to 20'),
      issue('seed[0].entities[1].count', 'count must be 0 to 10000'),
      issue('seed[0].entities[1].fields', 'Invoice.amount is required: give it a generator'),
      issue('seed[1].entities[0].fields[2].generator.min', 'min is greater than max'),
      issue('seed[1].entities[0].fields[2].generator.values[3]', 'must be a whole number'),
      issue('seed[1].entities[0].fields[2].generator.weights.paid', 'no chain of transitions'),
      issue('seed[1]', 'whole profile'),
      issue('settings[0].key', 'not ours'),
    ])
    expect(out.section).toEqual(['at most 5 seed profiles'])
    expect(out.rows[0].fields).toEqual({
      tenants: ['tenants must be 0 to 20'],
      'entities.1.count': ['count must be 0 to 10000'],
      'entities.1.fields': ['Invoice.amount is required: give it a generator'],
    })
    expect(out.rows[1].fields['entities.0.fields.2.generator.min']).toEqual(['min is greater than max'])
    expect(out.rows[1].fields['entities.0.fields.2.generator.values']).toEqual(['must be a whole number'])
    expect(out.rows[1].fields['entities.0.fields.2.generator.weights.paid']).toEqual(['no chain of transitions'])
    expect(out.rows[1].row).toEqual(['whole profile'])
    expect(normalizeKey('entities[0].fields[1].generator.values[4]')).toBe('entities.0.fields.1.generator.values')
  })
})

describe('how to run it', () => {
  it('shows the exact commands of the B1-9 generated CLI', () => {
    expect(runCommands('demo')).toEqual({
      seed: 'python -m app.seed --profile demo',
      reset: 'python -m app.seed --profile demo --reset',
      check: 'python -m app.seed --check',
    })
  })
})
