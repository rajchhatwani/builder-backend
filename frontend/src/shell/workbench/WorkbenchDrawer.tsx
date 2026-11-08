import { useEffect, useRef, useState } from 'react'
import { ApiReference } from './ApiReference'
import { RequestConsole } from './RequestConsole'
import { useOpenApi } from './useOpenApi'
import { PREVIEW_ORIGIN } from './previewOrigin'

type Tab = 'reference' | 'console'

/** Bottom drawer of the v2 shell. Stays mounted after first open (hidden when closed) so history survives
 *  closing it; remounts per project (key) so tokens and history never cross projects. */
export function WorkbenchDrawer({ projectId, open, onClose, origin = PREVIEW_ORIGIN }: { projectId: string; open: boolean; onClose: () => void; origin?: string | null }) {
  const [tab, setTab] = useState<Tab>('console')
  const [everOpened, setEverOpened] = useState(open)
  const ref = useRef<HTMLElement>(null)
  useEffect(() => { if (open) setEverOpened(true) }, [open])
  useEffect(() => { if (open) ref.current?.focus() }, [open])
  const { load, retry } = useOpenApi(origin, everOpened)
  if (!everOpened) return null

  return (
    <section
      id="workbench-drawer" ref={ref} tabIndex={-1} hidden={!open} className="wb-drawer"
      aria-label="Workbench" data-testid="workbench"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}
    >
      <header className="wb-head">
        <strong>Workbench</strong>
        <div role="group" aria-label="Workbench view" className="bh-tabs">
          <button type="button" className={tab === 'console' ? '' : 'outline'} aria-pressed={tab === 'console'} onClick={() => setTab('console')}>Request console</button>
          <button type="button" className={tab === 'reference' ? '' : 'outline'} aria-pressed={tab === 'reference'} onClick={() => setTab('reference')}>API reference</button>
        </div>
        <button type="button" className="ghost small" onClick={onClose}>Close <kbd>Esc</kbd></button>
      </header>
      <div className="wb-body">
        {!origin ? (
          <p className="muted" data-testid="wb-no-origin">
            No preview API is configured for this dashboard, so there is nothing to call yet. The preview runtime provides it
            (set <code>VITE_PREVIEW_API_ORIGIN</code> to a running generated project to try this now).
          </p>
        ) : load.status === 'loading' ? (
          <p role="status" aria-live="polite" data-testid="wb-loading">Loading the API description…</p>
        ) : load.status === 'error' ? (
          <div role="alert" data-variant="danger" className="bh-alert" data-testid="wb-error">
            {load.message} <button type="button" className="small" onClick={retry}>Retry</button>
          </div>
        ) : (
          <>
            <div hidden={tab !== 'console'}><RequestConsole projectId={projectId} origin={origin} doc={load.doc} /></div>
            {tab === 'reference' && <ApiReference doc={load.doc} origin={origin} />}
          </>
        )}
      </div>
    </section>
  )
}
