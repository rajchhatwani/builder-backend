import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { StateMachineBody } from '../../api/types'
import { NODE_H, NODE_W, layoutMachine, statesOf } from './layout'

/** The state machines of the two neutral example specs, read from the backend fixtures so the
 *  test data cannot drift from them. */
function machines(fixture: string): StateMachineBody[] {
  const file = resolve(__dirname, '../../../../tests/fixtures/specs', fixture)
  return JSON.parse(readFileSync(file, 'utf8')).state_machines
}

const FIXTURES = ['flow_invoices.json', 'flow_leave.json']

describe.each(FIXTURES)('layout of %s', (fixture) => {
  const all = machines(fixture)

  it('has one machine', () => expect(all).toHaveLength(1))

  it('is deterministic (same input, same output, also after a JSON round trip)', () => {
    const a = layoutMachine(all[0])
    const b = layoutMachine(structuredClone(all[0]))
    expect(b).toEqual(a)
    expect(layoutMachine(JSON.parse(JSON.stringify(all[0])))).toEqual(a)
  })

  it('places every state once with integer coordinates and no overlapping nodes', () => {
    const { nodes } = layoutMachine(all[0])
    expect(nodes.map((n) => n.id)).toEqual(statesOf(all[0]))
    for (const n of nodes) {
      expect(Number.isInteger(n.x) && Number.isInteger(n.y)).toBe(true)
      expect([n.width, n.height]).toEqual([NODE_W, NODE_H])
    }
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]
        const b = nodes[j]
        const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
        expect(overlap, `${a.id} overlaps ${b.id}`).toBe(false)
      }
    }
  })

  it('gives every edge a route and a label box that overlaps no node and no other label', () => {
    const { nodes, edges } = layoutMachine(all[0])
    const hit = (a: { x: number; y: number; width: number; height: number }, b: typeof a) =>
      a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
    const boxes = edges.map((e) => ({ id: e.id, x: e.label.x - e.label.width / 2, y: e.label.y - e.label.height / 2, width: e.label.width, height: e.label.height }))
    for (const e of edges) expect(e.points.length).toBeGreaterThanOrEqual(2)
    for (const b of boxes) for (const n of nodes) expect(hit(b, n), `label ${b.id} overlaps node ${n.id}`).toBe(false)
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        // labels of the same transition on different edges may sit anywhere; only distinct ones must not collide
        expect(hit(boxes[i], boxes[j]), `labels ${boxes[i].id} and ${boxes[j].id} overlap`).toBe(false)
      }
    }
  })

  it('has one edge per (transition, from state) and every edge joins two placed states', () => {
    const m = all[0]
    const { nodes, edges } = layoutMachine(m)
    const expected = m.transitions!.reduce((n, t) => n + (t.from_states?.length ?? 0), 0)
    expect(edges).toHaveLength(expected)
    expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length)
    const ids = new Set(nodes.map((n) => n.id))
    for (const e of edges) expect(ids.has(e.source) && ids.has(e.target)).toBe(true)
  })

  it('flows top to bottom: the initial state is on the top row', () => {
    const { nodes } = layoutMachine(all[0])
    const top = Math.min(...nodes.map((n) => n.y))
    expect(nodes.find((n) => n.initial)!.y).toBe(top)
  })

  it('matches the stored layout snapshot', () => {
    expect(layoutMachine(all[0])).toMatchSnapshot()
  })
})

describe('edge cases', () => {
  it('keeps two transitions between the same pair of states as two edges', () => {
    const { edges } = layoutMachine(machines('flow_invoices.json')[0])
    const pair = edges.filter((e) => e.source === 'pending_approval' && e.target === 'approved')
    expect(pair.map((e) => e.transition).sort()).toEqual(['approve', 'approve_large'])
  })
  it('lays out a machine with no transitions as the lone initial state', () => {
    const { nodes, edges } = layoutMachine({ entity: 'X', field: 's', initial: 'a' })
    expect(edges).toEqual([])
    expect(nodes.map((n) => n.id)).toEqual(['a'])
  })
})
