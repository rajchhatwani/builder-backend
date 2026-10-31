/** C0-F3: api/types.ts must not drift from the builder's OpenAPI schema (e2e/openapi.json, kept
 *  current by tests/unit/test_openapi_snapshot.py). Compared by name for every interface that
 *  has a schema of the same name:
 *   - "phantom": the UI reads a field the API does not send;
 *   - "optional-in-api": the UI treats a field as always present but the API may omit it.
 *  Drift that existed when this test was added is listed in e2e/drift-baseline.json and must
 *  only ever shrink; anything new fails. Regenerate the baseline with UPDATE_DRIFT_BASELINE=1. */
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const root = resolve(__dirname, '../..')
const openapi = JSON.parse(readFileSync(resolve(root, 'e2e/openapi.json'), 'utf8'))
const baselinePath = resolve(root, 'e2e/drift-baseline.json')

/** Interfaces whose OpenAPI schema has a different name. */
const ALIASES: Record<string, string> = { PaymentsSizingResult: 'PaymentsSizingRead' }

interface Prop {
  optional: boolean
}

function clientInterfaces(): Map<string, Map<string, Prop>> {
  const file = ts.createSourceFile('types.ts', readFileSync(resolve(root, 'src/api/types.ts'), 'utf8'), ts.ScriptTarget.Latest, true)
  const out = new Map<string, Map<string, Prop>>()
  for (const node of file.statements) {
    if (!ts.isInterfaceDeclaration(node) || node.heritageClauses) continue // `extends` is resolved by TS itself
    const props = new Map<string, Prop>()
    for (const m of node.members) {
      if (ts.isPropertySignature(m) && m.name) props.set(m.name.getText(file).replace(/['"]/g, ''), { optional: !!m.questionToken })
    }
    out.set(node.name.text, props)
  }
  return out
}

function drift(): string[] {
  const schemas: Record<string, { properties?: Record<string, unknown>; required?: string[] }> = openapi.components.schemas
  const found: string[] = []
  for (const [name, props] of clientInterfaces()) {
    const schema = schemas[ALIASES[name] ?? name]
    if (!schema?.properties) continue
    const required = new Set(schema.required ?? [])
    for (const [prop, info] of props) {
      if (!(prop in schema.properties)) found.push(`${name}.${prop}: phantom`)
      else if (!info.optional && !required.has(prop)) found.push(`${name}.${prop}: optional-in-api`)
    }
  }
  return found.sort()
}

describe('api/types.ts vs OpenAPI', () => {
  it('has no drift beyond the recorded baseline', () => {
    const now = drift()
    if (process.env.UPDATE_DRIFT_BASELINE === '1') writeFileSync(baselinePath, JSON.stringify(now, null, 1) + '\n')
    const baseline: string[] = JSON.parse(readFileSync(baselinePath, 'utf8'))
    expect(now.filter((d) => !baseline.includes(d)), 'new drift').toEqual([])
    expect(baseline.filter((d) => !now.includes(d)), 'fixed: remove from drift-baseline.json').toEqual([])
  })

  it('compares a meaningful number of interfaces', () => {
    const schemas = openapi.components.schemas
    const compared = [...clientInterfaces().keys()].filter((n) => schemas[ALIASES[n] ?? n]?.properties)
    expect(compared.length).toBeGreaterThan(30)
  })
})
