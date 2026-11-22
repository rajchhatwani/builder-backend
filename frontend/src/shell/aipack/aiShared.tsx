import { useEffect, useState, type ReactNode } from 'react'
import { PreviewSessionGate } from '../preview/PreviewSessionGate'
import { usePreviewSession } from '../preview/usePreviewSession'
import type { PreviewSession } from '../preview/previewSession'
import { UNEXPECTED, errText, ok2xx, type Call, type Load } from '../money/moneyShared'
import { aiErrorMessage } from './aiLogic'

/** GET `path` (null = do nothing). A response that arrives after the path changed or the page unmounted is dropped. */
export function useGet<T>(call: Call, path: string | null, check: (j: unknown) => boolean, what: string, refresh = 0): Load<T> {
  const [l, setL] = useState<Load<T>>({ s: 'idle' })
  useEffect(() => {
    if (path === null) { setL({ s: 'idle' }); return }
    let dead = false
    setL({ s: 'loading' })
    void (async () => {
      try {
        const r = await call('GET', path)
        if (dead) return
        setL(ok2xx(r.status) ? (check(r.json) ? { s: 'ok', v: r.json as T } : { s: 'error', m: UNEXPECTED }) : { s: 'error', m: aiErrorMessage(r.status, r.json, what) })
      } catch (e) { if (!dead) setL({ s: 'error', m: errText(e, `Could not reach the ${what}`) }) }
    })()
    return () => { dead = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call, path, refresh])
  return l
}

export const isObj = (j: unknown): j is Record<string, unknown> => !!j && typeof j === 'object' && !Array.isArray(j)
export const hasArray = (k: string) => (j: unknown) => isObj(j) && Array.isArray(j[k])
export const isArr = (j: unknown) => Array.isArray(j)

/** One h1, the preview-session gate, and the body. The body is remounted per project. */
export function AiPageFrame({ projectId, session, testid, title, intro, children }: {
  projectId: string; session?: PreviewSession; testid: string; title: string; intro: ReactNode
  children: (s: PreviewSession) => ReactNode
}) {
  const own = usePreviewSession(projectId, { disabled: !!session })
  const s = session ?? own
  return (
    <div data-testid={testid} className="stack">
      <h1>{title}</h1>
      <p className="muted">{intro}</p>
      <PreviewSessionGate session={s} prefix={testid.replace(/-page$/, '')}>
        <div key={projectId} className="stack">{children(s)}</div>
      </PreviewSessionGate>
    </div>
  )
}

export function Pager({ info, onPrev, onNext, id }: { info: { from: number; to: number; hasPrev: boolean; hasNext: boolean }; onPrev: () => void; onNext: () => void; id: string }) {
  return (
    <div className="hstack" data-testid={`${id}-pager`}>
      <button type="button" className="outline small" disabled={!info.hasPrev} onClick={onPrev} data-testid={`${id}-prev`}>Previous</button>
      <span className="muted" aria-live="polite">{info.from}-{info.to}</span>
      <button type="button" className="outline small" disabled={!info.hasNext} onClick={onNext} data-testid={`${id}-next`}>Next</button>
    </div>
  )
}
