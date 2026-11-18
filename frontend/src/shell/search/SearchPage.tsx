import { useEffect, useId, useState } from 'react'
import { api } from '../../api/client'
import { entitiesOf } from '../import/importLogic'

const msg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback)
type Hit = Record<string, unknown>

/** Searches the imported records of one entity (permission-filtered on the server) and rebuilds the search index. */
export function SearchPage({ projectId }: { projectId: string }) {
  const [entities, setEntities] = useState<string[] | null>(null)
  const [entity, setEntity] = useState('')
  const [roles, setRoles] = useState<string[]>([])
  const [role, setRole] = useState('')
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<{ items: Hit[]; total: number } | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [reindexing, setReindexing] = useState(false)
  const [reindex, setReindex] = useState<Record<string, unknown> | null>(null)
  const [reindexError, setReindexError] = useState<string | null>(null)
  const entityId = useId()
  const roleId = useId()
  const qId = useId()

  useEffect(() => {
    let off = false
    setLoadError(null)
    api.getSpecJson(projectId).then(
      (spec) => { if (!off) { const names = entitiesOf(spec).map((e) => e.name); setEntities(names); setEntity(names[0] ?? '') } },
      (e: unknown) => { if (!off) { setEntities(null); setLoadError(msg(e, 'Could not load the project')) } },
    )
    return () => { off = true }
  }, [projectId, attempt])

  useEffect(() => {
    let off = false
    api.getBehaviorRoles(projectId).then(
      (r) => { if (!off) { const names = r.roles.map((x) => x.name); setRoles(names); setRole('') } },
      () => { if (!off) { setRoles([]); setRole('') } },
    )
    return () => { off = true }
  }, [projectId])

  const search = async () => {
    if (!q.trim() || !entity) return
    setSearching(true); setError(null)
    try {
      const r = await api.searchProject(projectId, entity, q.trim(), 20, role || undefined)
      const items = Array.isArray(r.hits) ? (r.hits as Hit[]) : []
      setHits({ items, total: typeof r.total === 'number' ? r.total : items.length })
    } catch (e) { setHits(null); setError(msg(e, 'The search failed')) } finally { setSearching(false) }
  }
  const doReindex = async () => {
    setReindexing(true); setReindexError(null)
    try { setReindex(await api.reindexSearch(projectId)) } catch (e) { setReindex(null); setReindexError(msg(e, 'The reindex failed')) } finally { setReindexing(false) }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Search</h1>
          <p>Search the records you imported. Results only include what the role you pick is allowed to see.</p>
        </div>
      </div>
      {loadError && (
        <div className="card empty-hero" role="alert" data-testid="search-load-error">
          <p>{loadError}</p>
          <button onClick={() => setAttempt((n) => n + 1)} data-testid="search-retry">Try again</button>
        </div>
      )}
      {entities === null && !loadError && <p className="empty-state">Loading…</p>}
      {entities !== null && entities.length === 0 && <p className="empty-state" data-testid="search-noentities">Add an entity first, then import records to search.</p>}
      {entities !== null && entities.length > 0 && (
        <form className="card" role="search" aria-label="Search records" onSubmit={(e) => { e.preventDefault(); void search() }}>
          <div className="field">
            <label htmlFor={entityId}>Entity</label>
            <select id={entityId} value={entity} onChange={(e) => setEntity(e.target.value)} data-testid="search-entity">
              {entities.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          {roles.length > 0 && (
            <div className="field">
              <label htmlFor={roleId}>Search as role</label>
              <select id={roleId} value={role} onChange={(e) => setRole(e.target.value)} data-testid="search-role">
                <option value="">My own access</option>
                {roles.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor={qId}>Search for</label>
            <input id={qId} type="search" value={q} maxLength={200} onChange={(e) => setQ(e.target.value)} data-testid="search-input" />
          </div>
          <button type="submit" disabled={searching || !q.trim()} data-testid="search-run">{searching ? 'Searching…' : 'Search'}</button>
        </form>
      )}
      {error && <p role="alert" data-testid="search-error">{error}</p>}
      {hits && (
        <div className="card" data-testid="search-results" aria-live="polite">
          <p data-testid="search-total">{hits.total} {hits.total === 1 ? 'result' : 'results'}</p>
          {hits.items.length > 0 && (
            <ul aria-label="Search results">
              {hits.items.map((h, i) => (
                <li key={String(h.id ?? i)} data-testid="search-hit">
                  {Object.entries(h).filter(([k]) => k !== 'id').map(([k, v]) => `${k}: ${String(v)}`).join(', ') || String(h.id ?? '')}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="card">
        <h2>Search index</h2>
        <p>Rebuild the searchable view of your imported records after a bulk change.</p>
        <button className="outline" onClick={() => void doReindex()} disabled={reindexing} data-testid="search-reindex">{reindexing ? 'Rebuilding…' : 'Reindex'}</button>
        {reindexError && <p role="alert" data-testid="search-reindex-error">{reindexError}</p>}
        {reindex && <pre data-testid="search-reindex-result" aria-label="Reindex result">{JSON.stringify(reindex, null, 2)}</pre>}
      </div>
    </>
  )
}
