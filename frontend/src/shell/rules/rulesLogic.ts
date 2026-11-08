import type { ExpressionField, StateMachineBody } from '../../api/types'

const IDENT_CHAR = /[A-Za-z0-9_]/

/** The identifier being typed right before the caret ("" when none). A name glued to a number ("12ab")
 *  or to a dot is not an identifier prefix. */
export function prefixAt(text: string, caret: number): { start: number; prefix: string } {
  const head = text.slice(0, caret)
  const m = /[A-Za-z_][A-Za-z0-9_]*$/.exec(head)
  if (!m) return { start: caret, prefix: '' }
  const before = head[m.index - 1]
  if (before !== undefined && (/[0-9]/.test(before) || before === '.')) return { start: caret, prefix: '' }
  return { start: m.index, prefix: m[0] }
}

/** Fields whose name starts with the prefix (case-insensitive). With `force` (Ctrl+Space) an empty prefix lists all.
 *  A single suggestion that is already typed in full is not offered. */
export function suggest(fields: ExpressionField[], prefix: string, force = false): ExpressionField[] {
  if (!prefix && !force) return []
  const p = prefix.toLowerCase()
  const hits = fields.filter((f) => f.name.toLowerCase().startsWith(p)).sort((a, b) => a.name.localeCompare(b.name))
  if (hits.length === 1 && hits[0].name === prefix) return []
  return hits
}

export function applyCompletion(text: string, start: number, caret: number, name: string): { text: string; caret: number } {
  return { text: text.slice(0, start) + name + text.slice(caret), caret: start + name.length }
}

/** Wrap-around move in the suggestion list. */
export function moveActive(index: number, delta: 1 | -1, count: number): number {
  if (count === 0) return -1
  return (index + delta + count) % count
}

export interface ErrorSegments {
  before: string
  mark: string
  after: string
  /** The error is past the last character (expression ends too early): show a caret marker at the end. */
  atEnd: boolean
}

/** Split the text around the backend's error position: the whole identifier/number at that position, or one character. */
export function errorSegments(text: string, pos: number): ErrorSegments {
  if (pos >= text.length) return { before: text, mark: '', after: '', atEnd: true }
  const at = Math.max(0, pos)
  let end = at + 1
  if (IDENT_CHAR.test(text[at])) while (end < text.length && IDENT_CHAR.test(text[end])) end++
  return { before: text.slice(0, at), mark: text.slice(at, end), after: text.slice(end), atEnd: false }
}

export function typeLabel(type: string | null | undefined): string {
  if (type === 'bool') return 'true/false expression'
  return type ? `${type} expression` : 'expression'
}

export interface Guard {
  key: string
  entity: string
  transition: string
  when: string
}

/** Every transition with a guard, in machine order. */
export function guardsOf(machines: StateMachineBody[]): Guard[] {
  const out: Guard[] = []
  for (const m of machines) {
    for (const t of m.transitions ?? []) {
      if (t.when) out.push({ key: `${m.entity}/${t.name}`, entity: m.entity, transition: t.name, when: t.when })
    }
  }
  return out
}

/** Run `fn` over items with at most `limit` in flight, keeping the result order. */
export async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length)
  let next = 0
  const worker = async () => {
    while (next < items.length) {
      const i = next++
      out[i] = await fn(items[i])
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return out
}
