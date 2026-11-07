import type { RequirementItem, RequirementQuestion, RequirementsMap } from './types'

const KIND_ORDER = ['actor', 'entity', 'workflow', 'rule', 'integration', 'compliance', 'nonfunctional', 'out_of_scope']
export const KIND_LABEL: Record<string, string> = {
  actor: 'People and roles', entity: 'Data', workflow: 'Workflows', rule: 'Rules', integration: 'Integrations',
  compliance: 'Compliance', nonfunctional: 'Quality and limits', out_of_scope: 'Declared out of scope',
}
export const kindLabel = (k: string) => KIND_LABEL[k] ?? k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, ' ')

export interface ItemGroup { kind: string; label: string; items: RequirementItem[] }

/** Items grouped by kind: known kinds in a fixed order, unknown kinds after them alphabetically. Input order kept inside a group. */
export function groupItems(items: RequirementItem[]): ItemGroup[] {
  const by = new Map<string, RequirementItem[]>()
  for (const it of items) by.set(it.kind, [...(by.get(it.kind) ?? []), it])
  const rank = (k: string) => { const i = KIND_ORDER.indexOf(k); return i < 0 ? KIND_ORDER.length : i }
  return [...by.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((kind) => ({ kind, label: kindLabel(kind), items: by.get(kind)! }))
}

/** "contract.pdf, page 3, Payment terms" (plain text only). */
export function sourceLabel(it: Pick<RequirementItem, 'source_doc' | 'source_page' | 'source_section'>): string {
  const parts = [it.source_doc, it.source_page != null ? `page ${it.source_page}` : null, it.source_section].filter((p): p is string => !!p)
  return parts.length ? parts.join(', ') : 'Your prompt'
}

export const STATUS_LABEL: Record<string, string> = { open: 'Not covered yet', covered: 'Covered', out_of_scope: 'Out of scope' }
export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s

export const coveredByList = (it: Pick<RequirementItem, 'covered_by'>): string[] =>
  Array.isArray(it.covered_by) ? it.covered_by : it.covered_by ? [it.covered_by] : []

export interface Coverage { total: number; inScope: number; covered: number; outOfScope: number; open: number; pct: number }
export function coverage(items: RequirementItem[]): Coverage {
  const outOfScope = items.filter((i) => i.status === 'out_of_scope').length
  const covered = items.filter((i) => i.status === 'covered').length
  const inScope = items.length - outOfScope
  return { total: items.length, inScope, covered, outOfScope, open: inScope - covered, pct: inScope ? Math.round((covered / inScope) * 100) : 0 }
}

/** A question still needs a person: no answer yet and the assumption not accepted. */
export const isOpenQuestion = (q: RequirementQuestion) => q.state === 'open' && !q.answer
export const openQuestions = (qs: RequirementQuestion[]) => qs.filter(isOpenQuestion)

export interface StartCheck { canStart: boolean; needsConfirm: boolean; openCount: number; reason: string }
export function startCheck(map: RequirementsMap | null): StartCheck {
  if (!map || map.items.length === 0) return { canStart: false, needsConfirm: false, openCount: 0, reason: 'Add a prompt or documents first.' }
  if (!map.items.some((i) => i.status !== 'out_of_scope')) return { canStart: false, needsConfirm: false, openCount: 0, reason: 'Every item is out of scope.' }
  const openCount = openQuestions(map.questions).length
  return { canStart: true, needsConfirm: openCount > 0, openCount, reason: '' }
}

export const ALLOWED_EXT = ['pdf', 'txt', 'md']
export const MAX_FILE_BYTES = 20 * 1024 * 1024
export const MAX_FILES = 10
/** Which of the chosen files can be uploaded, and why not for the rest. */
export function checkFiles(files: Array<Pick<File, 'name' | 'size'>>): { ok: number[]; errors: string[] } {
  const ok: number[] = []
  const errors: string[] = []
  files.forEach((f, i) => {
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    if (!ALLOWED_EXT.includes(ext)) errors.push(`${f.name}: only PDF, text and Markdown files are accepted.`)
    else if (f.size > MAX_FILE_BYTES) errors.push(`${f.name}: larger than 20 MB.`)
    else if (f.size === 0) errors.push(`${f.name}: the file is empty.`)
    else if (ok.length >= MAX_FILES) errors.push(`${f.name}: at most ${MAX_FILES} files per upload.`)
    else ok.push(i)
  })
  return { ok, errors }
}
