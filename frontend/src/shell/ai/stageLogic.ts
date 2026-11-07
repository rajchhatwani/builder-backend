import { parseOperations, type Operation } from '../workbench/workbenchLogic'

/** Pure logic for the Stage tabs (code, logs, data). No React, no network. */

export type Zone = 'generated' | 'custom' | string
export interface WsFile { path: string; zone: Zone; size: number; editable: boolean }
export interface WsFileContent { path: string; zone: Zone; content: string; editable: boolean; sha256: string }

const LANGS: Record<string, string> = { py: 'python', json: 'json', yaml: 'yaml', yml: 'yaml', md: 'markdown', toml: 'ini', ini: 'ini', sql: 'sql', sh: 'shell', txt: 'plaintext' }
export function languageFor(path: string): string {
  const name = path.split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  if (dot < 0) return 'plaintext'
  return LANGS[name.slice(dot + 1).toLowerCase()] ?? 'plaintext'
}

export interface TreeNode { name: string; path: string; file?: WsFile; children: TreeNode[] }
/** Builds a sorted folder tree (folders first, then files, alphabetical). */
export function buildTree(files: WsFile[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', children: [] }
  for (const f of files) {
    let cur = root
    const parts = f.path.split('/').filter(Boolean)
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join('/')
      let next = cur.children.find((c) => c.path === path)
      if (!next) { next = { name: part, path, children: [] }; cur.children.push(next) }
      if (i === parts.length - 1) next.file = f
      cur = next
    })
  }
  const sort = (n: TreeNode) => {
    n.children.sort((a, b) => Number(!!a.file && !a.children.length) - Number(!!b.file && !b.children.length) || a.name.localeCompare(b.name))
    n.children.forEach(sort)
  }
  sort(root)
  return root.children
}

export function describeSaveError(status: number, code: string | undefined): string {
  if (status === 403 || code === 'file_not_editable') return 'This file is generated and cannot be edited. Change the spec instead.'
  if (code === 'file_changed') return 'The file changed since you opened it. Reload it to see the latest version; your edits are kept in the editor until then.'
  if (code === 'workspace_busy') return 'The workspace is busy (a build or run is using it). Try again in a moment.'
  if (status === 413) return 'This file is too large to edit here.'
  if (status >= 400 && status < 500) return 'This file cannot be edited here (binary, too large or not allowed).'
  return 'Saving failed. Try again.'
}

/* ---- logs ---- */
export const MAX_LOG_LINES = 2000
export interface LogLine { id: number; kind: 'log' | 'info' | 'state' | 'end'; text: string }

/** Appends lines and keeps only the newest MAX_LOG_LINES. */
export function pushLines(buf: LogLine[], add: LogLine[], max = MAX_LOG_LINES): LogLine[] {
  const all = buf.length ? buf.concat(add) : add
  return all.length > max ? all.slice(all.length - max) : all
}

/** Incremental SSE parser: feed text chunks, get complete events. Handles CRLF and chunk splits. */
export function createSseParser() {
  let pending = ''
  return (chunk: string): Array<{ event: string; data: string }> => {
    pending += chunk.replace(/\r\n?/g, '\n')
    const out: Array<{ event: string; data: string }> = []
    let i: number
    while ((i = pending.indexOf('\n\n')) >= 0) {
      const block = pending.slice(0, i)
      pending = pending.slice(i + 2)
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      }
      if (data.length || event !== 'message') out.push({ event, data: data.join('\n') })
    }
    return out
  }
}

export const BACKOFF_MS = [1000, 2000, 4000, 8000, 15000]
export const MAX_RECONNECTS = 6
export function backoffDelay(attempt: number): number { return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] }

/* ---- data browser ---- */
export interface Entity { name: string; listPath: string }
/** Collection endpoints: GET paths with no path parameters (and the generated list shape). */
export function discoverEntities(doc: unknown): Entity[] {
  const ops: Operation[] = parseOperations(doc)
  const seen = new Set<string>()
  const out: Entity[] = []
  for (const o of ops) {
    if (o.method !== 'get' || o.path.includes('{')) continue
    if (/^\/(openapi|docs|redoc|health|ready|metrics|auth|login|me)\b/.test(o.path) || o.path.startsWith('/-/')) continue
    if (seen.has(o.path)) continue
    seen.add(o.path)
    out.push({ name: o.path.replace(/^\//, ''), listPath: o.path })
  }
  return out.sort((a, b) => a.name.localeCompare(b.name))
}

export interface RowsPage { rows: Array<Record<string, unknown>>; columns: string[]; total: number | null }
/** Accepts a bare array or an object with items/results/data/rows. Returns null if the shape is not tabular. */
export function extractRows(body: unknown): RowsPage | null {
  let arr: unknown = body
  let total: number | null = null
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const o = body as Record<string, unknown>
    arr = ['items', 'results', 'data', 'rows'].map((k) => o[k]).find(Array.isArray)
    if (typeof o.total === 'number') total = o.total
    else if (typeof o.count === 'number') total = o.count
  }
  if (!Array.isArray(arr)) return null
  const rows = arr.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object' && !Array.isArray(r))
  const columns: string[] = []
  for (const r of rows.slice(0, 50)) for (const k of Object.keys(r)) if (!columns.includes(k)) columns.push(k)
  return { rows, columns: columns.slice(0, 40), total }
}

export function cellText(v: unknown): string {
  if (v === null || v === undefined) return ''
  const s = typeof v === 'object' ? JSON.stringify(v) : String(v)
  return s.length > 200 ? `${s.slice(0, 200)}…` : s
}

export const PAGE_SIZE = 25
export function pageQuery(page: number, size = PAGE_SIZE): string { return `limit=${size}&offset=${Math.max(0, page) * size}` }
