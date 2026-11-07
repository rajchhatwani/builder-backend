import { Component, Suspense, lazy, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { workspaceApi } from './workspaceApi'
import { buildTree, describeSaveError, languageFor, type TreeNode, type WsFile, type WsFileContent } from './stageLogic'

const MonacoEditor = lazy(() => import('./MonacoEditor'))

/** If Monaco fails to load (worker/bundle problem) fall back to a read-only <pre>. */
class EditorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}

export function ZoneBadge({ zone }: { zone: string }) {
  return <span className={`badge ${zone === 'custom' ? '' : 'badge-muted'}`} data-testid={`zone-${zone}`}>{zone === 'generated' ? '🔒 generated' : zone}</span>
}

function Tree({ nodes, open, selected, onPick, depth = 0 }: { nodes: TreeNode[]; open: Set<string>; selected: string | null; onPick: (n: TreeNode) => void; depth?: number }) {
  return (
    <ul role={depth === 0 ? 'tree' : 'group'} aria-label={depth === 0 ? 'Workspace files' : undefined} className="stage-tree">
      {nodes.map((n) => {
        const isDir = !n.file
        const expanded = open.has(n.path)
        return (
          <li key={n.path} role="treeitem" aria-expanded={isDir ? expanded : undefined} aria-selected={n.path === selected}>
            <button type="button" className="stage-tree-item" style={{ paddingInlineStart: `${depth * 12 + 4}px` }} data-testid={`file-${n.path}`}
              aria-current={n.path === selected ? 'true' : undefined} onClick={() => onPick(n)}>
              <span aria-hidden="true">{isDir ? (expanded ? '▾' : '▸') : '·'}</span> {n.name}
              {n.file && !n.file.editable && <span className="visually-hidden"> (read-only)</span>}
              {n.file && !n.file.editable && <span aria-hidden="true"> 🔒</span>}
            </button>
            {isDir && expanded && <Tree nodes={n.children} open={open} selected={selected} onPick={onPick} depth={depth + 1} />}
          </li>
        )
      })}
    </ul>
  )
}

export function CodeView({ projectId, workspaceId }: { projectId: string; workspaceId: string }) {
  const [files, setFiles] = useState<WsFile[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [file, setFile] = useState<WsFileContent | null>(null)
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'ok'; text: string; reload?: boolean } | null>(null)
  const draftRef = useRef(draft); draftRef.current = draft
  const fileRef = useRef(file); fileRef.current = file
  const savingRef = useRef(false)

  const loadList = useCallback(() => {
    setListError(null)
    workspaceApi.list(projectId, workspaceId).then(setFiles, (e: unknown) => setListError(e instanceof ApiError ? e.message : 'Could not load the files'))
  }, [projectId, workspaceId])
  useEffect(() => { setFiles(null); setFile(null); loadList() }, [loadList])

  const dirty = !!file && draft !== file.content
  const openFile = useCallback(async (path: string, force = false) => {
    if (!force && fileRef.current && draftRef.current !== fileRef.current.content && !window.confirm('Discard your unsaved changes?')) return
    setLoading(true); setMessage(null)
    try {
      const f = await workspaceApi.read(projectId, workspaceId, path)
      setFile(f); setDraft(f.content)
    } catch (e) {
      setMessage({ kind: 'error', text: e instanceof ApiError ? (e.status === 413 || e.status === 415 || e.status === 422 ? 'This file is binary or too large to show here.' : e.message) : 'Could not open the file' })
    } finally { setLoading(false) }
  }, [projectId, workspaceId])

  const save = useCallback(async () => {
    const f = fileRef.current
    if (!f || !f.editable || savingRef.current || draftRef.current === f.content) return
    savingRef.current = true; setSaving(true); setMessage(null)
    try {
      const saved = await workspaceApi.write(projectId, workspaceId, f.path, draftRef.current, f.sha256)
      setFile(saved); setDraft(saved.content === draftRef.current ? saved.content : draftRef.current)
      setMessage({ kind: 'ok', text: 'Saved' })
      loadList()
    } catch (e) {
      const err = e instanceof ApiError ? e : null
      setMessage({ kind: 'error', text: describeSaveError(err?.status ?? 0, err?.code), reload: err?.code === 'file_changed' })
    } finally { savingRef.current = false; setSaving(false) }
  }, [projectId, workspaceId, loadList])

  const pick = (n: TreeNode) => {
    if (n.file) { void openFile(n.path); return }
    setOpen((s) => { const x = new Set(s); if (x.has(n.path)) x.delete(n.path); else x.add(n.path); return x })
  }

  useEffect(() => {
    if (!dirty) return
    const h = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  const readOnly = !file?.editable
  const label = file ? `${readOnly ? 'Read-only ' : ''}editor for ${file.path}` : 'Editor'
  const pre = <pre className="stage-pre" data-testid="code-fallback" tabIndex={0} aria-label={label}>{draft}</pre>

  return (
    <div className="stage-code" data-testid="code-view">
      <nav className="stage-files" aria-label="Files">
        {listError && <p role="alert" className="error-text">{listError} <button type="button" className="btn btn-sm" onClick={loadList}>Retry</button></p>}
        {!files && !listError && <p className="muted small-text">Loading files…</p>}
        {files && files.length === 0 && <p className="muted small-text" data-testid="code-empty">This workspace has no files yet.</p>}
        {files && files.length > 0 && <Tree nodes={buildTree(files)} open={open} selected={file?.path ?? null} onPick={pick} />}
      </nav>
      <section className="stage-main" aria-label="File editor">
        {!file && !loading && <p className="muted" data-testid="code-pick">Pick a file to view it.</p>}
        {loading && <p className="muted small-text" role="status">Opening…</p>}
        {file && (
          <>
            <div className="hstack stage-bar">
              <strong data-testid="code-path">{file.path}</strong>
              <ZoneBadge zone={file.zone} />
              {dirty && <span className="badge badge-outline" data-testid="code-dirty">Unsaved changes</span>}
              {file.editable && <button type="button" className="btn btn-primary btn-sm" data-testid="code-save" disabled={!dirty || saving} onClick={() => void save()}>{saving ? 'Saving…' : 'Save'}</button>}
              {file.editable && <span className="muted small-text">Ctrl/Cmd+S</span>}
            </div>
            {!file.editable && <p className="muted small-text" data-testid="code-readonly-hint">Generated, edit the spec instead. This file is read-only.</p>}
            {message && (
              <p role={message.kind === 'error' ? 'alert' : 'status'} className={message.kind === 'error' ? 'error-text' : 'muted small-text'} data-testid="code-message">
                {message.text} {message.reload && <button type="button" className="btn btn-sm" data-testid="code-reload" onClick={() => void openFile(file.path, true)}>Reload latest</button>}
              </p>
            )}
            <EditorBoundary fallback={<><p className="muted small-text" data-testid="code-fallback-note">The code editor could not load, showing the file read-only.</p>{pre}</>}>
              <Suspense fallback={<p className="muted small-text" role="status">Loading editor…</p>}>
                <MonacoEditor path={file.path} language={languageFor(file.path)} value={draft} readOnly={readOnly || saving} onChange={setDraft} onSave={() => void save()} label={label} />
              </Suspense>
            </EditorBoundary>
          </>
        )}
      </section>
    </div>
  )
}
