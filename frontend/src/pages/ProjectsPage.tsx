import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { NewProjectDialog } from '../components/NewProjectDialog'
import { link } from '../components/Sidebar'
import { useUi } from '../components/Ui'

interface Summary {
  entities: number
  authOn: boolean
  problems: number
}

function ProjectCard({ project, onDelete }: { project: Project; onDelete: () => void }) {
  const [summary, setSummary] = useState<Summary | null>(null)

  useEffect(() => {
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
  }, [project.id])

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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const page = await api.listProjects(200, 0)
      setProjects(page.items)
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
            <ProjectCard key={p.id} project={p} onDelete={() => handleDelete(p)} />
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
