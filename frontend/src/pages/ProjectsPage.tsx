import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatDeletionDate } from '../api/dates'
import type { Organization, Project } from '../api/types'
import { NewProjectDialog } from '../components/NewProjectDialog'
import { link } from '../components/Sidebar'
import { useUi } from '../components/Ui'

interface Summary {
  entities: number
  authOn: boolean
  problems: number
}

interface ProjectCardProps {
  project: Project
  onDelete: () => void
  /** The project's org is waiting for deletion: every call about it would answer 423. */
  lockedOrg?: Organization
  /** The project's org requires two-factor and this session has none: every call would answer 403. */
  mfaOrg?: Organization
}

function ProjectCard({ project, onDelete, lockedOrg, mfaOrg }: ProjectCardProps) {
  const [summary, setSummary] = useState<Summary | null>(null)

  useEffect(() => {
    if (lockedOrg || mfaOrg) return
    let cancelled = false
    Promise.all([
      api.listEntities(project.id, 1, 0),
      api.getAuthConfig(project.id).catch(() => null),
      api.validateProject(project.id).catch(() => null),
    ]).then(([entities, auth, report]) => {
      if (cancelled) return
      setSummary({
        entities: entities.total,
        authOn: auth?.enabled ?? false,
        problems: report?.issues.length ?? 0,
      })
    })
    return () => {
      cancelled = true
    }
  }, [project.id, lockedOrg, mfaOrg])

  if (mfaOrg && !lockedOrg) {
    return (
      <div className="card project-card" onClick={() => (window.location.hash = '#/account')}>
        <div className="project-card-head">
          <h3>{project.name}</h3>
          <span className="badge badge-muted">Needs 2FA</span>
        </div>
        <p className="muted">
          {mfaOrg.name} requires two-factor authentication. Turn it on, then sign in again with your code.{' '}
          <a href="#/account" onClick={(e) => e.stopPropagation()}>
            Open your account
          </a>
        </p>
      </div>
    )
  }

  if (lockedOrg) {
    const orgPage = link(`/org/${encodeURIComponent(lockedOrg.slug)}`)
    return (
      <div className="card project-card" onClick={() => (window.location.hash = orgPage)}>
        <div className="project-card-head">
          <h3>{project.name}</h3>
          <span className="badge badge-muted">Locked</span>
        </div>
        <p className="muted">
          {lockedOrg.name} is scheduled for deletion on {formatDeletionDate(lockedOrg.deletion_scheduled_for)}, with
          this project.{' '}
          <a href={orgPage} onClick={(e) => e.stopPropagation()}>
            Open the organization
          </a>
        </p>
      </div>
    )
  }

  const open = link(`/p/${project.id}/overview`)

  return (
    <div className="card project-card" onClick={() => (window.location.hash = open)}>
      <div className="project-card-head">
        <h3>
          <a href={open} onClick={(e) => e.stopPropagation()}>
            {project.name}
          </a>
        </h3>
        {summary &&
          (summary.problems === 0 ? (
            <span className="badge status-ok">Ready</span>
          ) : (
            <span className="badge status-warn">
              {summary.problems} to fix
            </span>
          ))}
      </div>
      <p className="muted">
        {project.description || (summary ? describe(summary) : 'Loading…')}
      </p>
      {project.description && summary && <p className="muted small-text">{describe(summary)}</p>}
      <div className="project-card-foot">
        <span className="muted small-text">Updated {new Date(project.updated_at).toLocaleDateString()}</span>
        <button
          className="ghost small"
          data-variant="danger"
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
        >
          Delete
        </button>
      </div>
    </div>
  )
}

function describe(s: Summary): string {
  const entities = s.entities === 0 ? 'No entities yet' : `${s.entities} ${s.entities === 1 ? 'entity' : 'entities'}`
  return `${entities} · ${s.authOn ? 'Sign-in on' : 'No sign-in'}`
}

export function ProjectsPage() {
  const { confirm, toast } = useUi()
  const [projects, setProjects] = useState<Project[]>([])
  const [lockedOrgs, setLockedOrgs] = useState<Map<string, Organization>>(new Map())
  const [mfaOrgs, setMfaOrgs] = useState<Map<string, Organization>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const page = await api.listProjects(200, 0)
      setProjects(page.items)
      // Orgs waiting for deletion (locked cards) and orgs whose two-factor policy this session
      // doesn't meet: opening their projects would only answer 423 / 403.
      const orgs = (await api.listOrgs().catch(() => null))?.items ?? []
      setLockedOrgs(new Map(orgs.filter((o) => o.deletion_scheduled_for).map((o) => [o.id, o])))
      const strict = orgs.filter((o) => o.require_mfa)
      const sessionMfa = strict.length ? ((await api.mfaStatus().catch(() => null))?.session_mfa ?? true) : true
      setMfaOrgs(new Map(sessionMfa ? [] : strict.map((o) => [o.id, o])))
    } catch {
      setError("Can't reach the server. Make sure the backend is running, then try again.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function handleDelete(project: Project) {
    const ok = await confirm({
      title: `Delete "${project.name}"?`,
      message: 'Its entities, auth settings and roles are removed too. This cannot be undone.',
      confirmLabel: 'Delete project',
      danger: true,
    })
    if (!ok) return
    await api.deleteProject(project.id)
    toast(`Deleted "${project.name}".`)
    load()
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Projects</h1>
          <p>Each project is a backend you design here and download as ready-to-run code.</p>
        </div>
        {projects.length > 0 && <button onClick={() => setDialogOpen(true)}>New project</button>}
      </div>

      {loading && <p className="empty-state">Loading…</p>}

      {error && (
        <div role="alert" data-variant="danger">
          {error} <button className="outline small" onClick={load}>Try again</button>
        </div>
      )}

      {!loading && !error && projects.length === 0 && (
        <div className="card empty-hero">
          <h2>Build your first backend</h2>
          <p>
            Describe your data, choose how people sign in, and download a complete API with tests and Docker setup.
          </p>
          <button onClick={() => setDialogOpen(true)}>Create a project</button>
        </div>
      )}

      {!loading && !error && projects.length > 0 && (
        <div className="project-grid">
          {projects.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              onDelete={() => handleDelete(p)}
              lockedOrg={p.organization_id ? lockedOrgs.get(p.organization_id) : undefined}
              mfaOrg={p.organization_id ? mfaOrgs.get(p.organization_id) : undefined}
            />
          ))}
        </div>
      )}

      <NewProjectDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onCreated={(project) => {
          setDialogOpen(false)
          window.location.hash = link(`/p/${project.id}/overview`)
        }}
      />
    </>
  )
}
