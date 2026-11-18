import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

describe('index.css tokens (F-1221)', () => {
  it('uses only oat radius/surface tokens that exist', () => {
    expect(css).not.toMatch(/var\(--radius\)/)
    expect(css).not.toMatch(/var\(--surface-[12]\)/)
  })
})

describe('view-as banner stacking (F-1222)', () => {
  it('lifts toasts and the workbench drawer above the fixed banner', () => {
    expect(css).toMatch(/body\.is-viewing\s+\.toast-stack\s*\{[^}]*inset-block-end/)
    expect(css).toMatch(/body\.is-viewing\s+\.wb-drawer\s*\{[^}]*inset-block-end/)
  })
})
