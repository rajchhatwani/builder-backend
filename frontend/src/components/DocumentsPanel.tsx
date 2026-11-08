import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DocumentTemplate, DocumentsSettings, LibraryTemplate, SpecForPolicies, ValidationIssue } from '../api/types'
import { BlockEditor } from './documents/BlockEditor'
import type { Block, DocTemplateData } from './documents/blocks'
import { useUi } from './Ui'

const ID_RE = /^[a-z][a-z0-9_]{0,39}$/

function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^[^a-z]+/, '').slice(0, 40)
}

function Preview({ projectId, template, compute, initialData }: { projectId: string; template: DocTemplateData; compute: string | null; initialData: string }) {
  const [data, setData] = useState(initialData)
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const previous = useRef<string | null>(null)

  useEffect(() => () => {
    if (previous.current) URL.revokeObjectURL(previous.current)
  }, [])

  async function run() {
    setError(null)
    let parsed: Record<string, unknown>
    try {
      parsed = data.trim() === '' ? {} : JSON.parse(data)
    } catch {
      setError('The sample data must be valid JSON.')
      return
    }
    setBusy(true)
    try {
      const blob = await api.previewDocument(projectId, { template: template as unknown as Record<string, unknown>, data: parsed, compute })
      if (previous.current) URL.revokeObjectURL(previous.current)
      previous.current = URL.createObjectURL(blob)
      setUrl(previous.current)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not render the preview.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <label>
        Sample data (JSON) the placeholders read
        <textarea rows={8} spellCheck={false} value={data} onChange={(e) => setData(e.target.value)} />
      </label>
      <button type="button" disabled={busy} onClick={run} style={{ marginBlock: 'var(--space-2)' }}>
        {busy ? 'Rendering…' : 'Preview the PDF'}
      </button>
      {error && (
        <div role="alert" data-variant="danger">
          {error}
        </div>
      )}
      {url && <iframe title="Document preview" src={url} style={{ width: '100%', height: '34rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }} />}
      <p className="muted small-text">The preview uses the same engine as the generated API, so what you see is what it renders.</p>
    </div>
  )
}

/** PDF documents: pick from ten templates, edit blocks, preview, choose who may render. */
export function DocumentsPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const { toast, confirm } = useUi()
  const [settings, setSettings] = useState<DocumentsSettings | null>(null)
  const [form, setForm] = useState<DocumentsSettings | null>(null)
  const [library, setLibrary] = useState<LibraryTemplate[]>([])
  const [spec, setSpec] = useState<SpecForPolicies | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [editing, setEditing] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const [s, lib, sp, iss] = await Promise.all([api.getDocuments(projectId), api.documentsLibrary(projectId), api.getSpecForPolicies(projectId), api.documentsIssues(projectId)])
      setSettings(s)
      setForm(s)
      setLibrary(lib)
      setSpec(sp)
      setIssues(iss.issues)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the documents.')
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  if (error && !settings) {
    return (
      <div role="alert" data-variant="danger">
        {error}
      </div>
    )
  }
  if (!settings || !form) return <p className="empty-state">Loading…</p>

  const roles = (spec?.auth?.roles ?? []).map((r) => r.name)
  const entities = (spec?.entities ?? []).map((e) => e.name)
  const authOn = spec?.auth !== null && spec?.auth !== undefined
  const never = settings.version === 0

  const setTemplate = (index: number, next: DocumentTemplate) => setForm({ ...form, templates: form.templates.map((t, i) => (i === index ? next : t)) })

  function addFromLibrary(item: LibraryTemplate) {
    if (!form) return
    let id = item.id
    let n = 2
    while (form.templates.some((t) => t.id === id)) id = `${item.id}_${n++}`
    const added: DocumentTemplate = {
      id,
      title: item.title,
      kind: item.id,
      entity: null,
      compute: item.compute,
      roles: roles.length === 1 ? [...roles] : [],
      template: JSON.parse(JSON.stringify(item.template)),
    }
    setForm({ ...form, enabled: true, templates: [...form.templates, added] })
    setEditing(form.templates.length)
  }

  async function save(event?: React.FormEvent) {
    event?.preventDefault()
    if (!form || !settings) return
    setSaving(true)
    setError(null)
    try {
      const saved = await api.putDocuments(projectId, { ...form, expected_version: settings.version })
      setSettings(saved)
      setForm(saved)
      setIssues((await api.documentsIssues(projectId)).issues)
      onChanged()
      toast('Documents saved.')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        await load()
        setError('Someone else changed the documents. They were reloaded: apply your change again.')
      } else {
        setError(err instanceof Error ? err.message : 'Could not save.')
      }
    } finally {
      setSaving(false)
    }
  }

  async function remove(index: number) {
    if (!form) return
    const t = form.templates[index]
    if (!(await confirm({ title: `Remove “${t.title || t.id}”?`, message: 'The route disappears from the next generated project.', confirmLabel: 'Remove', danger: true }))) return
    setForm({ ...form, templates: form.templates.filter((_, i) => i !== index) })
    setEditing(null)
  }

  const current = editing !== null ? form.templates[editing] : null
  const sample = current ? library.find((l) => l.id === current.kind)?.sample : undefined

  return (
    <>
      {issues.length > 0 && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-4)' }}>
          <strong>
            {issues.length} problem{issues.length === 1 ? '' : 's'} to fix before you can generate
          </strong>
          <ul className="issue-list">
            {issues.map((issue, i) => (
              <li key={i}>
                <span>
                  {issue.message}
                  <small className="muted"> · {issue.path.replace('documents.', '')}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="card" onSubmit={save}>
        {error && (
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
            {error}
          </div>
        )}
        {!authOn && (
          <div role="alert" data-variant="warning" style={{ marginBlockEnd: 'var(--space-4)' }}>
            Documents are for signed-in people only (rendering costs CPU): turn on Authentication first.
          </div>
        )}
        <div className="toggle-field">
          <label>
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
            <span>
              <strong>Generate PDF documents (invoices, receipts, statements …)</strong>
              <br />
              <span className="muted small-text">
                {never ? 'Off until you save. Pick templates below; the next download then includes the routes.' : 'Turn off to stop generating the routes.'}
              </span>
            </span>
          </label>
        </div>
        <label style={{ maxWidth: '14rem', marginBlockStart: 'var(--space-3)' }}>
          Rate limit per client
          <input value={form.rate_limit} onChange={(e) => setForm({ ...form, rate_limit: e.target.value })} placeholder="30/minute" />
        </label>

        <h3 style={{ marginBlockStart: 'var(--space-5)' }}>Your templates</h3>
        {form.templates.length === 0 ? (
          <p className="empty-state">None yet. Add one from the library below.</p>
        ) : (
          <ul className="relation-list">
            {form.templates.map((t, i) => (
              <li key={t.id} style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <strong>{t.title || t.id}</strong> <code className="muted">/documents/{t.id}/{t.entity ? 'records/{id}' : 'render'}</code>
                  <div className="muted small-text">
                    Who may render: {t.roles.length > 0 ? t.roles.join(', ') : <strong>nobody yet: choose roles</strong>}
                    {t.entity && ` · bound to ${t.entity}`}
                  </div>
                </div>
                <div className="row-actions">
                  <button type="button" className="outline small" onClick={() => setEditing(editing === i ? null : i)}>
                    {editing === i ? 'Close' : 'Edit'}
                  </button>
                  <button type="button" className="outline small" onClick={() => remove(i)}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {current && editing !== null && (
          <div className="idp-card" style={{ marginBlockStart: 'var(--space-3)' }}>
            <div className="field-grid">
              <label>
                Title
                <input
                  value={current.title}
                  onChange={(e) => setTemplate(editing, { ...current, title: e.target.value, template: { ...current.template, title: current.template.title } })}
                />
              </label>
              <label>
                Name in the URL
                <input
                  value={current.id}
                  onChange={(e) => setTemplate(editing, { ...current, id: slugify(e.target.value) })}
                  aria-invalid={!ID_RE.test(current.id)}
                />
              </label>
            </div>
            <fieldset style={{ border: 0, padding: 0, marginBlockStart: 'var(--space-3)' }}>
              <legend>Who may render it</legend>
              <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
                {roles.length === 0 && <span className="muted small-text">Define roles under Authentication first.</span>}
                {roles.map((r) => (
                  <label key={r} style={{ display: 'inline-flex', gap: 'var(--space-1)', margin: 0 }}>
                    <input type="checkbox" checked={current.roles.includes(r)} onChange={(e) => setTemplate(editing, { ...current, roles: e.target.checked ? [...current.roles, r] : current.roles.filter((x) => x !== r) })} />
                    {r}
                  </label>
                ))}
              </div>
              <p className="muted small-text">An empty list means nobody. Roles inherited from another role count.</p>
            </fieldset>
            <div className="field-grid" style={{ marginBlockStart: 'var(--space-3)' }}>
              <label>
                Data comes from
                <select value={current.entity ?? ''} onChange={(e) => setTemplate(editing, { ...current, entity: e.target.value || null })}>
                  <option value="">The request (you send the data)</option>
                  {entities.map((n) => (
                    <option key={n} value={n}>
                      A stored {n} (placeholders: row.field)
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Recompute totals from the list
                <input value={current.compute ?? ''} placeholder="items (blank: none)" onChange={(e) => setTemplate(editing, { ...current, compute: e.target.value.trim() || null })} />
              </label>
            </div>
            <p className="muted small-text">
              {current.entity
                ? `A stored record is read through ${current.entity}'s own access rules, so nobody gets a PDF of a record they cannot read.`
                : 'Totals are always recomputed on the server from the line items; a total sent by the caller is ignored.'}
            </p>

            <h4>Page</h4>
            <div className="field-grid">
              <label>
                Size
                <select value={String(current.template.page?.size ?? 'A4')} onChange={(e) => setTemplate(editing, { ...current, template: { ...current.template, page: { ...current.template.page, size: e.target.value } } })}>
                  <option value="A4">A4</option>
                  <option value="LETTER">Letter</option>
                </select>
              </label>
              <label>
                Orientation
                <select value={String(current.template.page?.orientation ?? 'portrait')} onChange={(e) => setTemplate(editing, { ...current, template: { ...current.template, page: { ...current.template.page, orientation: e.target.value } } })}>
                  <option value="portrait">Portrait</option>
                  <option value="landscape">Landscape</option>
                </select>
              </label>
              <label>
                Footer (use {'{{page}}'} and {'{{pages}}'})
                <input value={String(current.template.footer ?? '')} onChange={(e) => setTemplate(editing, { ...current, template: { ...current.template, footer: e.target.value } })} />
              </label>
            </div>

            <h4>Content</h4>
            <BlockEditor blocks={current.template.blocks as Block[]} onChange={(blocks) => setTemplate(editing, { ...current, template: { ...current.template, blocks } })} />

            <h4>Preview</h4>
            <Preview key={current.id + (sample ? 's' : 'n')} projectId={projectId} template={current.template as DocTemplateData} compute={current.compute} initialData={JSON.stringify(sample ?? {}, null, 2)} />
          </div>
        )}

        <div style={{ marginBlockStart: 'var(--space-4)' }}>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>

      <div className="card" style={{ marginBlockStart: 'var(--space-4)' }}>
        <strong>Library: ten ready-made templates</strong>
        <p className="muted small-text">Adding one copies it into your project, where you can change everything. Nothing is linked back to the library.</p>
        <div className="choice-grid">
          {library.map((item) => (
            <div key={item.id} className="choice" style={{ cursor: 'default' }}>
              <strong>{item.title}</strong>
              <span className="muted small-text">{item.why}</span>
              <span className="small-text">
                {item.industries.map((i) => (
                  <span key={i} className="badge badge-outline">
                    {i}
                  </span>
                ))}
              </span>
              <button type="button" className="outline small" onClick={() => addFromLibrary(item)}>
                Add
              </button>
            </div>
          ))}
        </div>
        <p className="muted small-text" style={{ marginBlockStart: 'var(--space-3)' }}>
          Good to know: some countries now require a structured e-invoice (Factur-X, ZUGFeRD, XRechnung, Peppol), not just a PDF. Dates and thresholds
          differ by country and keep changing, so check your tax authority. These templates produce the readable PDF only. Fonts cover Latin scripts;
          Arabic, Indic and CJK text are not supported.
        </p>
      </div>
    </>
  )
}
