import type { SpecOp } from '../../api/types'

const WORDS: Record<string, string> = {
  add_entity: 'Added entity',
  update_entity: 'Changed entity',
  remove_entity: 'Removed entity',
  add_field: 'Added field',
  update_field: 'Changed field',
  remove_field: 'Removed field',
  add_relation: 'Added relation',
  update_relation: 'Changed relation',
  remove_relation: 'Removed relation',
  set_section: 'Replaced section',
  replace_spec: 'Replaced the whole spec',
}

const str = (v: unknown) => (typeof v === 'string' && v ? v : null)
const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null)

/** The thing an operation touched, from its payload, or null when the payload has no readable name. */
export function opTarget(op: Pick<SpecOp, 'op_type' | 'payload'>): string | null {
  const p = op.payload
  switch (op.op_type) {
    case 'add_entity':
      return str(obj(p.entity)?.name)
    case 'update_entity':
    case 'remove_entity':
      return str(p.name)
    case 'add_field': {
      const e = str(p.entity), f = str(obj(p.field)?.name)
      return e && f ? `${e}.${f}` : (e ?? f)
    }
    case 'update_field':
    case 'remove_field': {
      const e = str(p.entity), f = str(p.name)
      return e && f ? `${e}.${f}` : (e ?? f)
    }
    case 'add_relation': {
      const r = obj(p.relation)
      return str(r?.name) ?? str(r?.from_name)
    }
    case 'update_relation':
    case 'remove_relation': {
      const a = str(p.from_entity), b = str(p.from_name)
      return a && b ? `${a}.${b}` : (a ?? b)
    }
    case 'set_section':
      return str(p.section)?.replace(/_/g, ' ') ?? null
    default:
      return null
  }
}

/** One line for the list: what happened, to what. Never throws on an operation this UI does not know. */
export function opSummary(op: SpecOp): string {
  if (op.origin === 'restore') return `Restored the spec to version ${op.ref_seq ?? '?'}`
  const base = WORDS[op.op_type] ?? op.op_type.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
  const target = opTarget(op)
  const text = target ? `${base} ${target}` : base
  if (op.origin === 'undo') return `Undid: ${text}`
  if (op.origin === 'redo') return `Redid: ${text}`
  return text
}

export function actorLabel(op: Pick<SpecOp, 'actor'>): string {
  const a = op.actor
  if (a.email) return a.email
  if (a.kind === 'user') return a.user_id ? 'A user (since removed)' : 'A user'
  return a.kind.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

export function formatWhen(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const secs = Math.round((now.getTime() - d.getTime()) / 1000)
  if (secs >= 0 && secs < 60) return 'just now'
  if (secs >= 60 && secs < 3600) return `${Math.floor(secs / 60)} min ago`
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** Operations a restore to `toSeq` would take back, newest first. `ops` is newest first, as the API returns it. */
export function opsToUndo(ops: SpecOp[], toSeq: number): SpecOp[] {
  return ops.filter((o) => o.seq > toSeq)
}

export const latestSeq = (ops: SpecOp[]) => (ops.length ? ops[0].seq : 0)

/** Restore is offered for every version except the one the spec is already at. */
export const canRestore = (ops: SpecOp[], toSeq: number) => ops.length > 0 && toSeq >= 0 && toSeq < latestSeq(ops)

/** Words for what a restore takes back, e.g. "3 changes: 2 added entity, 1 changed field". */
export function impactText(undone: SpecOp[]): string {
  if (!undone.length) return 'Nothing: the spec is already at this version.'
  const counts = new Map<string, number>()
  for (const o of undone) {
    const w = (WORDS[o.op_type] ?? o.op_type.replace(/_/g, ' ')).toLowerCase()
    counts.set(w, (counts.get(w) ?? 0) + 1)
  }
  const parts = [...counts].map(([w, n]) => `${n} ${w}`)
  return `${undone.length} ${undone.length === 1 ? 'change' : 'changes'}: ${parts.join(', ')}`
}

/** A message the user can act on for a failed undo/redo/restore. `conflict` means: reload the log. */
export function failureMessage(err: unknown): { text: string; conflict: boolean } {
  const e = err as { status?: number; code?: string; message?: string } | null
  const code = e?.code
  if (code === 'spec_conflict') {
    return { conflict: true, text: 'Someone else changed the spec while you were working, so nothing was restored. The history was reloaded; check it and try again.' }
  }
  if (code === 'spec_changed') return { conflict: true, text: 'The spec was changed outside the history, so it cannot be restored safely. The history was reloaded.' }
  if (code === 'already_there') return { conflict: true, text: 'The spec is already at that version. The history was reloaded.' }
  if (code === 'nothing_to_undo') return { conflict: false, text: 'There is nothing to undo.' }
  if (code === 'nothing_to_redo') return { conflict: false, text: 'There is nothing to redo.' }
  if (e?.status === 403) return { conflict: false, text: 'You do not have permission to change this project.' }
  if (e?.status === 404) return { conflict: true, text: 'That version no longer exists. The history was reloaded.' }
  return { conflict: false, text: e?.message || 'The request failed. Nothing was changed.' }
}
