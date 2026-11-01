import dagre from '@dagrejs/dagre'
import type { StateMachineBody, TransitionBody } from '../../api/types'

/** Pure layout of one state machine (no React, no DOM): states are nodes, one edge per (transition, from-state).
 *  Same input always gives the same output (insertion order is fixed, coordinates are rounded). */
export const NODE_W = 160
export const NODE_H = 44

export interface LaidOutNode {
  id: string
  /** Top-left corner (React Flow convention), integers. */
  x: number
  y: number
  width: number
  height: number
  initial: boolean
}

export interface LaidOutEdge {
  /** `<transition>:<from>`; unique even when two transitions join the same pair of states. */
  id: string
  source: string
  target: string
  transition: string
  /** Route from the source to the target (dagre, avoids the nodes in between), integers. */
  points: { x: number; y: number }[]
  /** Label box (centre + size) that dagre reserved room for, so labels do not overlap. */
  label: { x: number; y: number; width: number; height: number }
}

export interface MachineLayout {
  nodes: LaidOutNode[]
  edges: LaidOutEdge[]
}

/** States in a stable order: the initial state, then every state in order of first appearance. */
export function statesOf(machine: StateMachineBody): string[] {
  const seen: string[] = []
  const add = (s: string) => {
    if (s && !seen.includes(s)) seen.push(s)
  }
  add(machine.initial)
  for (const t of machine.transitions ?? []) {
    for (const f of t.from_states ?? []) add(f)
    add(t.to_state)
  }
  return seen
}

/** Rough label size from the text (no DOM needed, so the layout is the same in tests and browsers). */
export function labelSize(t: TransitionBody): { width: number; height: number } {
  const chars = t.name.length + (t.auto ? 5 : 0)
  return { width: Math.round(chars * 7 + 24), height: 24 }
}

export function edgesOf(machine: StateMachineBody): Omit<LaidOutEdge, 'points' | 'label'>[] {
  const out: Omit<LaidOutEdge, 'points' | 'label'>[] = []
  for (const t of machine.transitions ?? []) {
    for (const f of t.from_states ?? []) {
      out.push({ id: `${t.name}:${f}`, source: f, target: t.to_state, transition: t.name })
    }
  }
  return out
}

export function layoutMachine(machine: StateMachineBody): MachineLayout {
  const g = new dagre.graphlib.Graph({ multigraph: true })
  g.setGraph({ rankdir: 'TB', nodesep: 40, ranksep: 40, marginx: 16, marginy: 16 })
  g.setDefaultEdgeLabel(() => ({}))
  const states = statesOf(machine)
  for (const s of states) g.setNode(s, { width: NODE_W, height: NODE_H })
  const sizes = new Map((machine.transitions ?? []).map((t) => [t.name, labelSize(t)]))
  const raw = edgesOf(machine)
  for (const e of raw) g.setEdge(e.source, e.target, { ...sizes.get(e.transition)!, labelpos: 'c' }, e.id)
  dagre.layout(g)
  const edges: LaidOutEdge[] = raw.map((e) => {
    const laid = g.edge(e.source, e.target, e.id)
    const { width, height } = sizes.get(e.transition)!
    return {
      ...e,
      points: laid.points.map((p: { x: number; y: number }) => ({ x: Math.round(p.x), y: Math.round(p.y) })),
      label: { x: Math.round(laid.x), y: Math.round(laid.y), width, height },
    }
  })
  const nodes = states.map((id) => {
    const n = g.node(id)
    return {
      id,
      x: Math.round(n.x - NODE_W / 2),
      y: Math.round(n.y - NODE_H / 2),
      width: NODE_W,
      height: NODE_H,
      initial: id === machine.initial,
    }
  })
  return { nodes, edges }
}
