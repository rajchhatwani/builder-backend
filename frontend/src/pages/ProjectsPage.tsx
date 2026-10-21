import { useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { DataTable } from '../components/DataTable'
import { NewProjectDialog } from '../components/NewProjectDialog'

interface ProjectsPageProps {
  onOpenProject: (project: Project) => void
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function ProjectsPage({ onOpenProject }: ProjectsPageProps) {
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
      setError('Could not reach the Builder API. Is it running on port 8000?')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function handleDelete(project: Project, event: React.MouseEvent) {
    event.stopPropagation()
    if (!window.confirm(`Delete project "${project.name}"? This cannot be undone.`)) return
    api.deleteProject(project.id).then(load)
  }

  const columns = useMemo<ColumnDef<Project>[]>(
    () => [
      { accessorKey: 'name', header: 'Name' },
      { accessorKey: 'slug', header: 'Slug' },
      { accessorKey: 'db_engine', header: 'Engine' },
      { accessorKey: 'version', header: 'Version' },
      {
        accessorKey: 'created_at',
        header: 'Created',
        cell: (ctx) => formatDate(ctx.getValue<string>()),
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="row-actions">
            <button
              className="outline small"
              data-variant="danger"
              onClick={(e) => handleDelete(row.original, e)}
            >
              Delete
            </button>
          </div>
        ),
      },
    ],
    [],
  )

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Projects</h1>
          <p>Backends built from a spec of entities, fields, and relations.</p>
        </div>
        <button onClick={() => setDialogOpen(true)}>New project</button>
      </div>

      <div className="stat-grid">
        <div className="card stat-card">
          <div className="stat-value">{projects.length}</div>
          <div className="stat-label">Projects</div>
        </div>
      </div>

      <div className="card">
        {loading && <p className="empty-state">Loading…</p>}
        {error && (
          <div role="alert" data-variant="danger">
            {error}
          </div>
        )}
        {!loading && !error && (
          <DataTable
            columns={columns}
            data={projects}
            emptyMessage="No projects yet. Create one to get started."
            onRowClick={onOpenProject}
          />
        )}
      </div>

      <NewProjectDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onCreated={(project) => {
          setDialogOpen(false)
          setProjects((prev) => [project, ...prev])
        }}
      />
    </>
  )
}
