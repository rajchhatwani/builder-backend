import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError } from '../api/client'
import type {
  DownloadMode,
  Project,
  ProjectRole,
  StorageBackend,
  StorageConfig,
  StorageImpact,
  StorageRoles,
  StorageWrite,
  ValidationIssue,
} from '../api/types'
import { Modal } from './Modal'
import { useUi } from './Ui'

interface StoragePanelProps {
  project: Project
  roles: ProjectRole[]
  authEnabled: boolean
  issues: ValidationIssue[] | null
  /** Called after anything changed so the project page can reload. */
  onChanged: () => void
}

const BACKENDS: Record<StorageBackend, { title: string; help: string }> = {
  s3: {
    title: 'Amazon S3',
    help: 'A bucket on AWS. Use an IAM role for the service; no access keys need to exist.',
  },
  minio: {
    title: 'MinIO / self-hosted S3',
    help: 'Any server that speaks the S3 API: a MinIO you run, Ceph, SeaweedFS, Garage. The download also starts a local development store.',
  },
}

const DOWNLOADS: Record<DownloadMode, { title: string; help: string }> = {
  proxy: {
    title: 'Through your API (recommended)',
    help: 'Your API streams the file and controls every header. The bucket is never exposed to browsers.',
  },
  presigned: {
    title: 'Direct from the bucket',
    help: 'Your API checks access, then redirects to a link that works for 60 seconds. Faster for big files, but the bucket must be reachable by your users.',
  },
}

const ROLE_ROWS: { key: keyof StorageRoles; label: string; help: string }[] = [
  { key: 'upload', label: 'Upload files', help: 'Who may send files in.' },
  { key: 'share', label: 'Share a file with everyone who can read', help: 'Marks a file as readable by all readers (e.g. product images).' },
  { key: 'read', label: 'Download their own and shared files', help: 'Usually the same people who upload, plus the people who view.' },
  { key: 'read_all', label: 'Download every file', help: 'Support or compliance staff (within a tenant).' },
  { key: 'delete', label: 'Delete their own files', help: 'Erasure requests and mistakes.' },
  { key: 'delete_all', label: 'Delete any file', help: 'Administrators.' },
  { key: 'operate', label: 'Operate the system', help: 'See audit trails and scanner health; block or unblock a file.' },
]

const TYPE_GROUPS: { label: string; types: string[] }[] = [
  { label: 'Images', types: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'] },
  { label: 'PDF', types: ['application/pdf'] },
  {
    label: 'Office documents',
    types: [
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ],
  },
  { label: 'Text and CSV', types: ['text/plain', 'text/csv'] },
  { label: 'Archives', types: ['application/zip', 'application/gzip'] },
]

interface Form {
  backend: StorageBackend
  bucket: string
  region: string
  keyPrefix: string
  allowedTypes: string
  maxFileMb: number
  userQuotaMb: string
  uploadsPerHour: number
  downloadMode: DownloadMode
  allowInlineImages: boolean
  roles: StorageRoles
  auditRetentionDays: number
  auditIp: boolean
  rescanAfterDays: number
  scanTimeoutSeconds: number
}

const EMPTY_ROLES: StorageRoles = {
  upload: [],
  share: [],
  read: [],
  read_all: [],
  delete: [],
  delete_all: [],
  operate: [],
}

const DEFAULT_FORM: Form = {
  backend: 's3',
  bucket: '',
  region: 'eu-west-1',
  keyPrefix: 'uploads',
  allowedTypes: '',
  maxFileMb: 25,
  userQuotaMb: '',
  uploadsPerHour: 60,
  downloadMode: 'proxy',
  allowInlineImages: false,
  roles: EMPTY_ROLES,
  auditRetentionDays: 2555,
  auditIp: true,
  rescanAfterDays: 30,
  scanTimeoutSeconds: 120,
}

function formFrom(c: StorageConfig): Form {
  return {
    backend: c.backend,
    bucket: c.bucket,
    region: c.region ?? '',
    keyPrefix: c.key_prefix,
    allowedTypes: c.allowed_types.join('\n'),
    maxFileMb: c.max_file_mb,
    userQuotaMb: c.user_quota_mb === null ? '' : String(c.user_quota_mb),
    uploadsPerHour: c.uploads_per_hour,
    downloadMode: c.download_mode,
    allowInlineImages: c.allow_inline_images,
    roles: c.roles,
    auditRetentionDays: c.security.audit_retention_days,
    auditIp: c.security.audit_ip,
    rescanAfterDays: c.security.rescan_after_days,
    scanTimeoutSeconds: c.security.scan_timeout_seconds,
  }
}

function lines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

function toWrite(f: Form): StorageWrite {
  const quota = f.userQuotaMb.trim()
  return {
    backend: f.backend,
    bucket: f.bucket.trim(),
    region: f.region.trim() === '' ? null : f.region.trim(),
    key_prefix: f.keyPrefix.trim(),
    allowed_types: lines(f.allowedTypes),
    max_file_mb: Number(f.maxFileMb),
    user_quota_mb: quota === '' ? null : Number(quota),
    uploads_per_hour: Number(f.uploadsPerHour),
    download_mode: f.downloadMode,
    allow_inline_images: f.allowInlineImages,
    roles: f.roles,
    security: {
      audit_retention_days: Number(f.auditRetentionDays),
      audit_ip: f.auditIp,
      rescan_after_days: Number(f.rescanAfterDays),
      scan_timeout_seconds: Number(f.scanTimeoutSeconds),
    },
  }
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

function Section({ title, children, open = true }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details open={open} className="auth-section">
      <summary>{title}</summary>
      <div className="auth-section-body">{children}</div>
    </details>
  )
}

export function StoragePanel({ project, roles, authEnabled, issues, onChanged }: StoragePanelProps) {
  const { toast } = useUi()
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<StorageConfig | null>(null)
  const [form, setForm] = useState<Form>(DEFAULT_FORM)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [switching, setSwitching] = useState<'enable' | 'disable' | null>(null)

  const active = config?.enabled === true

  async function load() {
    setLoading(true)
    try {
      const loaded = await api.getStorage(project.id)
      setConfig(loaded)
      setForm(formFrom(loaded))
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setConfig(null)
        setForm(DEFAULT_FORM)
      } else {
        setMessage({ ok: false, text: errorText(err, 'Could not load the file upload settings.') })
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [project.id])

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function setRole(key: keyof StorageRoles, name: string, on: boolean) {
    const current = form.roles[key]
    set('roles', { ...form.roles, [key]: on ? [...current, name] : current.filter((r) => r !== name) })
  }

  function addTypes(types: string[]) {
    const have = new Set(lines(form.allowedTypes))
    types.forEach((t) => have.add(t))
    set('allowedTypes', [...have].join('\n'))
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const saved = await api.putStorage(project.id, toWrite(form))
      setConfig(saved)
      setForm(formFrom(saved))
      toast('File upload settings saved.')
      onChanged()
    } catch (err) {
      setMessage({ ok: false, text: errorText(err, 'Could not save the file upload settings.') })
    } finally {
      setSaving(false)
    }
  }

  const storageIssues = useMemo(
    () =>
      (issues ?? []).filter(
        (i) => i.path === 'storage' || i.path.startsWith('storage.') || i.code === 'storage_required',
      ),
    [issues],
  )
  const roleNames = roles.map((r) => r.name)
  const anyType = lines(form.allowedTypes).length === 0

  if (loading) {
    return (
      <div className="card">
        <p className="empty-state">Loading…</p>
      </div>
    )
  }

  return (
    <>
      <div className="card status-card" data-active={active ? 'true' : undefined}>
        <div className="status-card-text">
          <strong>{active ? 'File uploads are on for this project' : 'File uploads are off for this project'}</strong>
          <p className="muted">
            {active
              ? 'The next download includes the file API, a malware scanner, an audit trail and setup notes for your bucket.'
              : config
                ? 'Your settings are saved: turn file uploads on when you are ready.'
                : 'Fill in the settings below, then turn file uploads on.'}
          </p>
        </div>
        {active ? (
          <button className="outline" data-variant="danger" onClick={() => setSwitching('disable')}>
            Turn off…
          </button>
        ) : (
          <button
            disabled={!config || !authEnabled}
            title={!config ? 'Save the settings first' : !authEnabled ? 'Turn on authentication first' : undefined}
            onClick={() => setSwitching('enable')}
          >
            Turn on…
          </button>
        )}
      </div>

      {!config && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <h3>What you get</h3>
          <ul className="benefit-list">
            <li>
              <strong>Any file type, scanned before it is stored.</strong> Every upload goes through ClamAV first. If the scanner is down the
              upload is refused, never let through. Infected files never reach your bucket.
            </li>
            <li>
              <strong>Nothing is trusted from the client.</strong> The type is decided from the file's bytes, names are cleaned and never used
              as paths, size is capped while the file arrives, and files are served as downloads with locked-down headers.
            </li>
            <li>
              <strong>Built for audits.</strong> Role-based access (and tenant isolation), a tamper-evident audit trail kept at least a year,
              erasure that really removes the bytes, periodic rescans, and a threat model in the zip.
            </li>
            <li>
              <strong>No secrets here.</strong> Bucket credentials are environment variables of the generated project; they are never stored
              in this dashboard or in the zip.
            </li>
          </ul>
        </div>
      )}

      {!authEnabled && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <div role="alert" data-variant="danger">
            File uploads need people to sign in. Turn on authentication first (Authentication or Keycloak).
          </div>
        </div>
      )}

      {storageIssues.length > 0 && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-3)' }}>
            {storageIssues.length} {storageIssues.length === 1 ? 'thing needs' : 'things need'} fixing before you can generate.
          </div>
          <ul className="issue-list">
            {storageIssues.map((issue, i) => (
              <li key={i}>
                <span>
                  {issue.message}
                  <small className="muted"> · {issue.path.replace('storage.', '')}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="card" onSubmit={handleSave}>
        {message && (
          <div role="alert" data-variant={message.ok ? 'success' : 'danger'} style={{ marginBlockEnd: 'var(--space-4)' }}>
            {message.text}
          </div>
        )}

        <Section title="Where files are kept">
          <div className="choice-grid">
            {(Object.keys(BACKENDS) as StorageBackend[]).map((id) => (
              <label key={id} className="choice" data-selected={form.backend === id ? 'true' : undefined}>
                <input type="radio" name="backend" checked={form.backend === id} onChange={() => set('backend', id)} />
                <strong>{BACKENDS[id].title}</strong>
                <span className="muted">{BACKENDS[id].help}</span>
              </label>
            ))}
          </div>
          {form.backend === 'minio' && (
            <p className="muted small-text" style={{ marginBlockStart: 'var(--space-3)' }}>
              <strong>About MinIO:</strong> its community edition stopped publishing container images in October 2025 and the repository was
              archived. Your project only speaks the S3 API, so a MinIO you already run (or build yourself) works, and so does any compatible
              server. For local development the download starts SeaweedFS instead.
            </p>
          )}
          <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
            <label>
              Bucket name
              <input
                value={form.bucket}
                placeholder="my-app-uploads"
                onChange={(e) => set('bucket', e.target.value)}
                pattern="[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"
              />
            </label>
            <label>
              Region {form.backend === 'minio' && '(optional)'}
              <input value={form.region} placeholder="eu-west-1" onChange={(e) => set('region', e.target.value)} />
            </label>
            <label>
              Folder inside the bucket
              <input value={form.keyPrefix} onChange={(e) => set('keyPrefix', e.target.value)} />
            </label>
          </div>
          <p className="muted small-text">
            Use a bucket of its own: the credentials you create should only be able to touch this folder. The download includes the bucket
            policy, the least-privilege IAM policy and the lifecycle rules.
          </p>
        </Section>

        <Section title="What is accepted">
          <div className="field-grid">
            <label>
              Largest file (MB)
              <input type="number" min={1} max={1024} value={form.maxFileMb} onChange={(e) => set('maxFileMb', Number(e.target.value))} />
            </label>
            <label>
              Storage per user (MB, optional)
              <input
                type="number"
                min={1}
                value={form.userQuotaMb}
                placeholder="No limit"
                onChange={(e) => set('userQuotaMb', e.target.value)}
              />
            </label>
            <label>
              Uploads per user per hour
              <input
                type="number"
                min={1}
                max={10000}
                value={form.uploadsPerHour}
                onChange={(e) => set('uploadsPerHour', Number(e.target.value))}
              />
            </label>
          </div>
          <label style={{ marginBlockStart: 'var(--space-4)' }}>
            Only accept these types (one per line; leave empty to accept any type)
            <textarea
              rows={4}
              value={form.allowedTypes}
              placeholder={'image/*\napplication/pdf'}
              onChange={(e) => set('allowedTypes', e.target.value)}
            />
          </label>
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', marginBlockStart: 'var(--space-2)' }}>
            {TYPE_GROUPS.map((g) => (
              <button key={g.label} type="button" className="outline small" onClick={() => addTypes(g.types)}>
                + {g.label}
              </button>
            ))}
          </div>
          <p className="muted small-text">
            {anyType
              ? 'Any type is accepted. Every file is still checked, scanned for malware, stored under a random name and served as a download.'
              : 'The check uses what the file really is (from its bytes), not its name or the type the sender claims.'}
          </p>
          <div role="note" className="card" style={{ marginBlockStart: 'var(--space-3)' }}>
            <strong>Malware scanning is always on.</strong> It cannot be switched off: a file that cannot be scanned is refused.
          </div>
        </Section>

        <Section title="How files are downloaded">
          <div className="choice-grid">
            {(Object.keys(DOWNLOADS) as DownloadMode[]).map((id) => (
              <label key={id} className="choice" data-selected={form.downloadMode === id ? 'true' : undefined}>
                <input
                  type="radio"
                  name="download"
                  checked={form.downloadMode === id}
                  onChange={() => set('downloadMode', id)}
                />
                <strong>{DOWNLOADS[id].title}</strong>
                <span className="muted">{DOWNLOADS[id].help}</span>
              </label>
            ))}
          </div>
          <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', marginBlockStart: 'var(--space-4)' }}>
            <input
              type="checkbox"
              checked={form.allowInlineImages}
              onChange={(e) => set('allowInlineImages', e.target.checked)}
            />
            Let browsers show plain images (PNG, JPEG, GIF, WebP) inline. Everything else is always a download.
          </label>
        </Section>

        <Section title="Who can do what">
          <p className="muted">
            Nothing is allowed to anyone unless you tick it. A file someone may not see answers exactly like a file that does not exist.
          </p>
          <div className="table">
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  {roleNames.map((r) => (
                    <th key={r}>{r}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROLE_ROWS.map((row) => (
                  <tr key={row.key}>
                    <td>
                      <strong>{row.label}</strong>
                      <br />
                      <small className="muted">{row.help}</small>
                    </td>
                    {roleNames.map((r) => (
                      <td key={r}>
                        <input
                          type="checkbox"
                          aria-label={`${row.label}: ${r}`}
                          checked={form.roles[row.key].includes(r)}
                          onChange={(e) => setRole(row.key, r, e.target.checked)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {roleNames.length === 0 && <p className="muted">Create roles first (Roles &amp; access).</p>}
          <p className="muted small-text">
            Upload, read, delete and operate need at least one role each: someone must be able to erase a file and someone must be able to
            read the audit trail.
          </p>
        </Section>

        <Section title="Security and compliance" open={false}>
          <div className="field-grid">
            <label>
              Keep the audit trail for (days, at least 365)
              <input
                type="number"
                min={365}
                value={form.auditRetentionDays}
                onChange={(e) => set('auditRetentionDays', Number(e.target.value))}
              />
            </label>
            <label>
              Rescan files not scanned for (days)
              <input
                type="number"
                min={1}
                max={365}
                value={form.rescanAfterDays}
                onChange={(e) => set('rescanAfterDays', Number(e.target.value))}
              />
            </label>
            <label>
              Longest a scan may take (seconds)
              <input
                type="number"
                min={5}
                max={600}
                value={form.scanTimeoutSeconds}
                onChange={(e) => set('scanTimeoutSeconds', Number(e.target.value))}
              />
            </label>
          </div>
          <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', marginBlockStart: 'var(--space-4)' }}>
            <input type="checkbox" checked={form.auditIp} onChange={(e) => set('auditIp', e.target.checked)} />
            Record the caller's IP address in the audit trail
          </label>
          <p className="muted small-text">
            IP addresses are personal data in many places. The trail never stores file contents or file names, only ids, hashes, sizes and
            types. Compliance depends on how you run the system: the download explains what the design covers and what it does not.
          </p>
        </Section>

        <footer className="form-actions" style={{ marginBlockStart: 'var(--space-4)' }}>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save file upload settings'}
          </button>
        </footer>
      </form>

      <SwitchDialog
        projectId={project.id}
        action={switching}
        onClose={() => setSwitching(null)}
        onDone={() => {
          setSwitching(null)
          load()
          onChanged()
        }}
      />
    </>
  )
}

function SwitchDialog({
  projectId,
  action,
  onClose,
  onDone,
}: {
  projectId: string
  action: 'enable' | 'disable' | null
  onClose: () => void
  onDone: () => void
}) {
  const { toast } = useUi()
  const [impact, setImpact] = useState<StorageImpact | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setImpact(null)
    setError(null)
    if (action === null) return
    api
      .storageImpact(projectId, action)
      .then(setImpact)
      .catch((err) => setError(errorText(err, 'Could not check what this changes.')))
  }, [action, projectId])

  async function confirm(event: FormEvent) {
    event.preventDefault()
    if (action === null) return
    setBusy(true)
    setError(null)
    try {
      await api.switchStorage(projectId, action)
      toast(action === 'enable' ? 'File uploads are on.' : 'File uploads are off. Your settings are kept.')
      onDone()
    } catch (err) {
      setError(errorText(err, 'Could not switch.'))
    } finally {
      setBusy(false)
    }
  }

  const turningOn = action === 'enable'
  return (
    <Modal open={action !== null} onClose={onClose}>
      <form onSubmit={confirm}>
        <header>
          <h3>{turningOn ? 'Turn on file uploads?' : 'Turn off file uploads?'}</h3>
          <p>
            {turningOn
              ? 'The next download will include the file API, a malware scanner and setup notes.'
              : 'The next download will not include file uploads.'}
          </p>
        </header>
        <div>
          {error && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              {error}
            </div>
          )}
          {!impact && !error && <p className="muted">Checking what this changes…</p>}
          {impact && impact.blockers.length > 0 && (
            <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
              <div>
                <strong>Not possible yet</strong>
                <ul className="impact-list">
                  {impact.blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {impact && impact.warnings.length > 0 && (
            <>
              <strong>Before you continue</strong>
              <ul className="impact-list">
                {impact.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </>
          )}
        </div>
        <footer>
          <button type="button" className="outline" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" data-variant={turningOn ? undefined : 'danger'} disabled={busy || !impact || !impact.can_proceed}>
            {busy ? 'Working…' : turningOn ? 'Turn on file uploads' : 'Turn off file uploads'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}
