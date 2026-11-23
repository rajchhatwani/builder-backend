import { useCallback } from 'react'
import type { PreviewSession } from '../preview/previewSession'
import { parseMoneyJson } from './moneyLogic'

export type Load<T> = { s: 'idle' } | { s: 'loading' } | { s: 'error'; m: string } | { s: 'ok'; v: T }
export type Page<T> = { items: T[]; total: number }
export type Call = (method: string, path: string, body?: unknown) => Promise<{ status: number; json: unknown }>

export const isPage = (j: unknown): j is Page<unknown> => !!j && typeof j === 'object' && Array.isArray((j as { items?: unknown }).items)
export const ok2xx = (s: number) => s >= 200 && s < 300
export const UNEXPECTED = 'The API answered with something unexpected. Check that this is the generated project API.'
export const errText = (e: unknown, f: string) => (e instanceof Error ? e.message : f)

/** JSON-aware request over the preview session; `*_minor` integers survive beyond 2^53 (as strings). */
export function useCall(session: PreviewSession): Call {
  const { request } = session
  return useCallback(async (method, path, body) => {
    const r = await request(method, path, body)
    let json: unknown = null
    try { json = r.text ? parseMoneyJson(r.text) : null } catch { json = null }
    return { status: r.status, json }
  }, [request])
}

export function State<T>({ l, id, empty, emptyText, children }: { l: Load<T>; id: string; empty: (v: T) => boolean; emptyText: string; children: (v: T) => React.ReactNode }) {
  if (l.s === 'idle') return null
  if (l.s === 'loading') return <p role="status" className="muted" data-testid={`${id}-loading`}>Loading…</p>
  if (l.s === 'error') return <p role="alert" className="error-text" data-testid={`${id}-error`}>{l.m}</p>
  if (empty(l.v)) return <p className="muted" data-testid={`${id}-empty`}>{emptyText}</p>
  return <>{children(l.v)}</>
}
