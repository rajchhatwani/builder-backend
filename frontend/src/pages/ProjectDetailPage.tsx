import { useEffect, useMemo, useState } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { api } from '../api/client'
import type { Entity, Project, ProjectRole, Relation } from '../api/types'
import { AuthConfigPanel } from '../components/AuthConfigPanel'
import { AuthCustomFieldsPanel } from '../components/AuthCustomFieldsPanel'
import { DataTable } from '../components/DataTable'
import { EntityDetail } from '../components/EntityDetail'
import { GeneratePanel } from '../components/GeneratePanel'
import { NewEntityDialog } from '../components/NewEntityDialog'
import { NewRelationDialog } from '../components/NewRelationDialog'
import { PermissionsPanel } from '../components/PermissionsPanel'
import { RolesPanel } from '../components/RolesPanel'

interface ProjectDetailPageProps {
  project: Project
  onBack: () => void
}

type TopTab = 'schema' | 'auth'
type AuthSubTab = 'config' | 'roles' | 'permissions' | 'custom-fields'

export function ProjectDetailPage({ project, onBack }: ProjectDetailPageProps) {
  const [entities, setEntities] = useState<Entity[]>([])
  const [relations, setRelations] = useState<Relation[]>([])
  const [roles, setRoles] = useState<ProjectRole[]>([])
  const [loading, setLoading] = useState(true)
  const [entityDialogOpen, setEntityDialogOpen] = useState(false)
  const [relationDialogOpen, setRelationDialogOpen] = useState(false)
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null)
  // Bumped on every reload so the generate panel drops results for an outdated model.
  const [modelVersion, setModelVersion] = useState(0)

  const [topTab, setTopTab] = useState<TopTab>('schema')
  const [authSubTab, setAuthSubTab] = useState<AuthSubTab>('config')

  async function load() {
    setLoading(true)
    const [entityPage, relationPage] = await Promise.all([
      api.listEntities(project.id, 200, 0),
      api.listRelations(project.id, 200, 0),
    ])
    setEntities(entityPage.items)
    setRelations(relationPage.items)
    setModelVersion((v) => v + 1)
    setLoading(false)
  }

  async function loadRoles() {
    const page = await api.listRoles(project.id, 200, 0)
    setRoles(page.items)
  }

  useEffect(() => {
    load()
    loadRoles()
  }, [project.id])

  function handleDeleteEntity(entity: Entity, event: React.MouseEvent) {
    event.stopPropagation()
    if (!window.confirm(`Delete entity "${entity.name}"?`)) return
    api.deleteEntity(entity.id).then(load)
  }

  function handleDeleteRelation(relation: Relation, event: React.MouseEvent) {
    event.stopPropagation()
    if (!window.confirm(`Delete this ${relation.kind} relation?`)) return
    api.deleteRelation(relation.id).then(load)
  }

  const entityColumns = useMemo<ColumnDef<Entity>[]>(
    () => [
      { accessorKey: 'name', header: 'Name' },
      { accessorKey: 'table_name', header: 'Table' },
      { accessorKey: 'plural_path', header: 'Path' },
      {
        id: 'operations',
        header: 'Operations',
        enableSorting: false,
        cell: ({ row }) => row.original.options.operations.join(', '),
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
              onClick={(e) => handleDeleteEntity(row.original, e)}
            >
              Delete
            </button>
          </div>
        ),
      },
    ],
    [],
  )

  const entityNameById = useMemo(() => {
    const map = new Map<string, string>()
    for (const entity of entities) map.set(entity.id, entity.name)
    return map
  }, [entities])

  const relationColumns = useMemo<ColumnDef<Relation>[]>(
    () => [
      { accessorKey: 'kind', header: 'Kind' },
      {
        id: 'from',
        header: 'From',
        cell: ({ row }) => entityNameById.get(row.original.from_entity_id) ?? row.original.from_entity_id,
      },
      {
        id: 'to',
        header: 'To',
        cell: ({ row }) => entityNameById.get(row.original.to_entity_id) ?? row.original.to_entity_id,
      },
      { accessorKey: 'from_name', header: 'From name' },
      { accessorKey: 'to_name', header: 'To name' },
      { accessorKey: 'on_delete', header: 'On delete' },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="row-actions">
            <button
              className="outline small"
              data-variant="danger"
              onClick={(e) => handleDeleteRelation(row.original, e)}
            >
              Delete
            </button>
          </div>
        ),
      },
    ],
    [entityNameById],
  )

  const selectedEntity = entities.find((e) => e.id === selectedEntityId)
  if (selectedEntity) {
    return (
      <EntityDetail
        entity={selectedEntity}
        onBack={() => setSelectedEntityId(null)}
        onChanged={load}
      />
    )
  }

  return (
    <>
      <button className="ghost small breadcrumb-back" onClick={onBack}>
        ← Back to projects
      </button>

      <div className="page-header">
        <div>
          <h1>{project.name}</h1>
          <p>
            <code>{project.slug}</code> &middot; {project.db_engine} &middot; v{project.version}
          </p>
        </div>
        {topTab === 'schema' && (
          <button onClick={() => setEntityDialogOpen(true)}>New entity</button>
        )}
      </div>

      {/* ── Top-level tabs ──────────────────────────────────────────────── */}
      <div className="tab-bar">
        <button
          className="tab-btn"
          aria-selected={topTab === 'schema'}
          onClick={() => setTopTab('schema')}
        >
          Schema
        </button>
        <button
          className="tab-btn"
          aria-selected={topTab === 'auth'}
          onClick={() => setTopTab('auth')}
        >
          Auth
        </button>
      </div>

      {topTab === 'schema' && (
        <>
          <div className="stat-grid">
            <div className="card stat-card">
              <div className="stat-value">{entities.length}</div>
              <div className="stat-label">Entities</div>
            </div>
            <div className="card stat-card">
              <div className="stat-value">{relations.length}</div>
              <div className="stat-label">Relations</div>
            </div>
          </div>

          <h3>Entities</h3>
          <p style={{ color: 'var(--muted-foreground)' }}>Open an entity to edit its fields and API options.</p>
          <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
            {loading ? (
              <p className="empty-state">Loading…</p>
            ) : (
              <DataTable
                columns={entityColumns}
                data={entities}
                onRowClick={(entity) => setSelectedEntityId(entity.id)}
                emptyMessage="No entities yet. Add one to start shaping this backend."
              />
            )}
          </div>

          <div className="table-toolbar">
            <h3>Relations</h3>
            <button className="outline small" onClick={() => setRelationDialogOpen(true)}>
              New relation
            </button>
          </div>
          <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
            {loading ? (
              <p className="empty-state">Loading…</p>
            ) : (
              <DataTable
                columns={relationColumns}
                data={relations}
                emptyMessage="No relations yet. Link two entities above."
              />
            )}
          </div>

          <GeneratePanel project={project} modelVersion={modelVersion} />

          <NewEntityDialog
            open={entityDialogOpen}
            projectId={project.id}
            onClose={() => setEntityDialogOpen(false)}
            onCreated={() => {
              setEntityDialogOpen(false)
              load()
            }}
          />

          <NewRelationDialog
            open={relationDialogOpen}
            projectId={project.id}
            entities={entities}
            onClose={() => setRelationDialogOpen(false)}
            onCreated={() => {
              setRelationDialogOpen(false)
              load()
            }}
          />
        </>
      )}

      {topTab === 'auth' && (
        <>
          {/* ── Auth sub-tabs ────────────────────────────────────────────── */}
          <div className="tab-bar auth-subtabs">
            <button
              className="tab-btn"
              aria-selected={authSubTab === 'config'}
              onClick={() => setAuthSubTab('config')}
            >
              Config
            </button>
            <button
              className="tab-btn"
              aria-selected={authSubTab === 'roles'}
              onClick={() => setAuthSubTab('roles')}
            >
              Roles
            </button>
            <button
              className="tab-btn"
              aria-selected={authSubTab === 'permissions'}
              onClick={() => setAuthSubTab('permissions')}
            >
              Permissions
            </button>
            <button
              className="tab-btn"
              aria-selected={authSubTab === 'custom-fields'}
              onClick={() => setAuthSubTab('custom-fields')}
            >
              Custom Fields
            </button>
          </div>

          {authSubTab === 'config' && <AuthConfigPanel projectId={project.id} />}
          {authSubTab === 'roles' && <RolesPanel projectId={project.id} />}
          {authSubTab === 'permissions' && (
            <PermissionsPanel
              projectId={project.id}
              entities={entities}
              roles={roles}
            />
          )}
          {authSubTab === 'custom-fields' && <AuthCustomFieldsPanel projectId={project.id} />}
        </>
      )}
    </>
  )
}
