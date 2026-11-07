import { useRef, useState, type KeyboardEvent } from 'react'
import { ApiError } from '../../api/client'
import { CodeView } from './CodeView'
import { DataBrowser } from './DataBrowser'
import { RunLogs } from './RunLogs'
import { workspaceApi } from './workspaceApi'

const TABS = [{ id: 'code', label: 'Code' }, { id: 'run', label: 'Run & logs' }, { id: 'data', label: 'Data' }] as const
type TabId = (typeof TABS)[number]['id']

/** The Stage: Code, Run & logs and Data for one draft workspace / preview. The preview token is memory-only state. */
export function StageTabs({ projectId, workspaceId, previewId, token: initialToken = '' }: { projectId: string; workspaceId: string; previewId?: string; token?: string }) {
  const [tab, setTab] = useState<TabId>('code')
  const [token, setToken] = useState(initialToken)
  const [tokenError, setTokenError] = useState<string | null>(null)
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  const onKey = (e: KeyboardEvent) => {
    const i = TABS.findIndex((t) => t.id === tab)
    const n = e.key === 'ArrowRight' ? (i + 1) % TABS.length : e.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : -1
    if (n < 0) return
    e.preventDefault(); setTab(TABS[n].id); refs.current[TABS[n].id]?.focus()
  }
  const issue = async () => {
    if (!previewId) return
    setTokenError(null)
    try { setToken((await workspaceApi.rotateToken(projectId, previewId)).token) }
    catch (e) { setTokenError(e instanceof ApiError ? e.message : 'Could not issue a token') }
  }

  const needsPreview = tab !== 'code'
  return (
    <section className="stage" aria-label="Stage" data-testid="stage-tabs">
      <div role="tablist" aria-label="Stage" className="stage-tablist" onKeyDown={onKey}>
        {TABS.map((t) => (
          <button key={t.id} ref={(el) => { refs.current[t.id] = el }} type="button" role="tab" id={`stage-tab-${t.id}`} aria-selected={tab === t.id} aria-controls={`stage-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1} data-testid={`stage-tab-${t.id}`} className={`stage-tab${tab === t.id ? ' is-active' : ''}`} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      <div role="tabpanel" id={`stage-panel-${tab}`} aria-labelledby={`stage-tab-${tab}`} className="stage-panel">
        {needsPreview && !previewId && <p className="muted" data-testid="stage-nopreview">No preview is running for this workspace yet. Start a preview to see logs and data.</p>}
        {needsPreview && previewId && (
          <div className="hstack stage-bar stage-token">
            <label htmlFor="stage-token">Preview token</label>
            <input id="stage-token" data-testid="stage-token" type="password" autoComplete="off" spellCheck={false} value={token} onChange={(e) => setToken(e.target.value)} placeholder="shown once when the preview started" />
            <button type="button" className="btn btn-sm" data-testid="stage-issue-token" onClick={() => void issue()}>Issue new token</button>
            {tokenError && <span role="alert" className="error-text small-text">{tokenError}</span>}
          </div>
        )}
        {tab === 'code' && <CodeView projectId={projectId} workspaceId={workspaceId} />}
        {tab === 'run' && previewId && <RunLogs previewId={previewId} token={token} />}
        {tab === 'data' && previewId && <DataBrowser previewId={previewId} token={token} />}
      </div>
    </section>
  )
}
