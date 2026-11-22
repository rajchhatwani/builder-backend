import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { useRawText } from '../../forms/useRawText'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import { UNEXPECTED, errText, isPage, ok2xx, type Call, type Load } from '../money/moneyShared'
import { degText, opsErrorMessage, parseDegrees, parseWhole, wholeText, type LL } from './opsLogic'

export { State, isPage, ok2xx, useCall, type Call, type Load, type Page } from '../money/moneyShared'
export const isObj = (j: unknown): boolean => !!j && typeof j === 'object' && !Array.isArray(j)

/** GET `path` (null = do not load). A newer path or unmount discards a late answer. Returns [state, reload]. */
export function useGet<T>(call: Call, path: string | null, what: string, shape: (j: unknown) => boolean = isPage): readonly [Load<T>, () => void] {
  const [l, setL] = useState<Load<T>>({ s: 'idle' })
  const [n, setN] = useState(0)
  useEffect(() => {
    if (path === null) { setL({ s: 'idle' }); return }
    let dead = false
    setL({ s: 'loading' })
    call('GET', path).then((r) => {
      if (dead) return
      if (ok2xx(r.status)) setL(shape(r.json) ? { s: 'ok', v: r.json as T } : { s: 'error', m: UNEXPECTED })
      else setL({ s: 'error', m: opsErrorMessage(r.status, r.json, what) })
    }, (e) => { if (!dead) setL({ s: 'error', m: errText(e, `Could not reach the ${what} API`) }) })
    return () => { dead = true }
  }, [call, path, what, shape, n])
  return [l, useCallback(() => setN((x) => x + 1), [])] as const
}

/** A request that must succeed: returns the JSON, or throws an Error carrying the clear message. */
export async function must(call: Call, method: string, path: string, body: unknown, what: string): Promise<unknown> {
  const r = await call(method, path, body)
  if (!ok2xx(r.status)) throw new Error(opsErrorMessage(r.status, r.json, what))
  return r.json
}

/** One-at-a-time mutation guard: a second click while one runs is ignored (also within the same tick). */
export function useAction() {
  const lock = useRef(false)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const run = useCallback(async (fn: () => Promise<string | void>): Promise<boolean> => {
    if (lock.current) return false
    lock.current = true
    setBusy(true); setError(null); setDone(null)
    try {
      const m = await fn()
      if (alive.current) setDone(m || null)
      return true
    } catch (e) {
      if (alive.current) setError(errText(e, 'Something went wrong'))
      return false
    } finally {
      lock.current = false
      if (alive.current) setBusy(false)
    }
  }, [])
  const clear = useCallback(() => { setError(null); setDone(null) }, [])
  return { busy, error, done, run, clear, fail: setError }
}
export type Action = ReturnType<typeof useAction>

export function Feedback({ a, id }: { a: Action; id: string }) {
  return (
    <>
      {a.error && <p role="alert" className="error-text" data-testid={`${id}-error`}>{a.error}</p>}
      {a.done && <p role="status" data-testid={`${id}-ok`}>{a.done}</p>}
    </>
  )
}

/** Decimal-degree input: the raw text survives each keystroke ("-", "40.", "-0.0") while the held value is integer micro-degrees. */
export function DegInput({ id, label, value, onChange, limit, testid }: { id: string; label: string; value: number | null; onChange: (micro: number | null) => void; limit: number; testid?: string }) {
  const parse = (t: string) => parseDegrees(t, limit)
  const [text, setText] = useRawText<number | null>(value, parse, degText)
  const bad = text.trim() !== '' && parse(text) === null
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <input id={id} value={text} inputMode="decimal" autoComplete="off" aria-invalid={bad || undefined} data-testid={testid}
        onChange={(e) => { setText(e.target.value); onChange(parse(e.target.value)) }} />
    </>
  )
}

/** Whole-number input with the same raw-text behaviour. */
export function WholeInput({ id, label, value, onChange, min, max, testid }: { id: string; label: string; value: number | null; onChange: (n: number | null) => void; min: number; max: number; testid?: string }) {
  const parse = (t: string) => parseWhole(t, min, max)
  const [text, setText] = useRawText<number | null>(value, parse, wholeText)
  const bad = text.trim() !== '' && parse(text) === null
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <input id={id} value={text} inputMode="numeric" autoComplete="off" aria-invalid={bad || undefined} data-testid={testid}
        onChange={(e) => { setText(e.target.value); onChange(parse(e.target.value)) }} />
    </>
  )
}

/** Latitude + longitude of one point. */
export function PointInput({ legend, value, onChange, testid }: { legend: string; value: LL; onChange: (p: LL) => void; testid: string }) {
  const id = useId()
  return (
    <fieldset className="hstack" data-testid={testid}>
      <legend>{legend}</legend>
      <DegInput id={`${id}-lat`} label="Latitude" value={value.lat} limit={90} testid={`${testid}-lat`} onChange={(lat) => onChange({ ...value, lat })} />
      <DegInput id={`${id}-lng`} label="Longitude" value={value.lng} limit={180} testid={`${testid}-lng`} onChange={(lng) => onChange({ ...value, lng })} />
    </fieldset>
  )
}

/** Inline confirmation before a destructive or bulk action. */
export function Confirm({ text, yes, onYes, onNo, busy, testid }: { text: string; yes: string; onYes: () => void; onNo: () => void; busy: boolean; testid: string }) {
  return (
    <div role="alertdialog" aria-label="Confirm" className="hstack" data-testid={testid}>
      <span>{text}</span>
      <button type="button" disabled={busy} onClick={onYes} data-testid={`${testid}-yes`}>{busy ? 'Working…' : yes}</button>
      <button type="button" className="outline" disabled={busy} onClick={onNo}>Cancel</button>
    </div>
  )
}

/** Page frame: exactly one h1, then the preview-session gate (sign-in) around the page body. */
export function OpsPage({ projectId, session, testid, title, intro, children }: {
  projectId: string; session?: PreviewSession; testid: string; title: string; intro: string
  children: (s: PreviewSession) => React.ReactNode
}) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <div data-testid={testid} className="stack">
      <h1>{title}</h1>
      <p className="muted">{intro}</p>
      <PreviewSessionGate session={s} prefix={testid}>{children(s)}</PreviewSessionGate>
    </div>
  )
}
