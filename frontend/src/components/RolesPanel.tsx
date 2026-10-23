import { useState, useEffect, useMemo } from 'react'
import type { ColumnDef } from '@tanstack/react-table'
import { api, ApiError } from '../api/client'
import type { ProjectRole, ProjectRoleCreate } from '../api/types'
import { DataTable } from './DataTable'
import { Modal } from './Modal'
import { useUi } from './Ui'

interface RolesPanelProps {
  projectId: string
}

export function RolesPanel({ projectId }: RolesPanelProps) {
  const { confirm } = useUi()
  const [roles, setRoles] = useState<ProjectRole[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<ProjectRole | null>(null)

  // Form fields
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [selfAssignable, setSelfAssignable] = useState(false)
  const [inviteOnly, setInviteOnly] = useState(false)
  const [inheritsFrom, setInheritsFrom] = useState('')
  const [position, setPosition] = useState<number | string>(0)

  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function load() {
    setLoading(true)
    api
      .listRoles(projectId, 200, 0)
      .then((page) => {
        setRoles(page.items)
        setError(null)
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load roles.')
      })
      .finally(() => {
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
  }, [projectId])

  function handleOpenCreate() {
    setEditing(null)
    setName('')
    setLabel('')
    setIsDefault(false)
    setSelfAssignable(false)
    setInviteOnly(false)
    setInheritsFrom('')
    setPosition(0)
    setFormError(null)
    setDialogOpen(true)
  }

  function handleOpenEdit(role: ProjectRole) {
    setEditing(role)
    setName(role.name)
    setLabel(role.label)
    setIsDefault(role.is_default)
    setSelfAssignable(role.self_assignable)
    setInviteOnly(role.invite_only)
    setInheritsFrom(role.inherits_from ?? '')
    setPosition(role.position)
    setFormError(null)
    setDialogOpen(true)
  }

  function handleCloseDialog() {
    setDialogOpen(false)
    setEditing(null)
    setFormError(null)
  }

  async function handleDelete(role: ProjectRole) {
    if (!(await confirm({ title: `Delete role "${role.name}"?`, confirmLabel: 'Delete', danger: true }))) return
    api
      .deleteRole(role.id)
      .then(load)
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to delete role.')
      })
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    try {
      const inherits = inheritsFrom.trim() || null
      const pos = typeof position === 'number' ? position : Number(position) || 0

      if (editing) {
        await api.updateRole(editing.id, {
          label,
          is_default: isDefault,
          self_assignable: selfAssignable,
          invite_only: inviteOnly,
          inherits_from: inherits,
          position: pos,
        })
      } else {
        const data: ProjectRoleCreate = {
          name,
          label,
          is_default: isDefault,
          self_assignable: selfAssignable,
          invite_only: inviteOnly,
          inherits_from: inherits,
          position: pos,
        }
        await api.createRole(projectId, data)
      }
      handleCloseDialog()
      load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setFormError('A role with this name already exists.')
      } else {
        setFormError(err instanceof Error ? err.message : 'Something went wrong.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const columns = useMemo<ColumnDef<ProjectRole>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Name',
      },
      {
        accessorKey: 'label',
        header: 'Label',
      },
      {
        accessorKey: 'is_default',
        header: 'Default',
        cell: ({ row }) => (row.original.is_default ? 'yes' : ''),
      },
      {
        accessorKey: 'self_assignable',
        header: 'Self assignable',
        cell: ({ row }) => (row.original.self_assignable ? 'yes' : ''),
      },
      {
        accessorKey: 'invite_only',
        header: 'Invite only',
        cell: ({ row }) => (row.original.invite_only ? 'yes' : ''),
      },
      {
        accessorKey: 'inherits_from',
        header: 'Inherits from',
        cell: ({ row }) => row.original.inherits_from || '—',
      },
      {
        accessorKey: 'position',
        header: 'Position',
      },
      {
        id: 'actions',
        header: '',
        enableSorting: false,
        cell: ({ row }) => (
          <div className="row-actions">
            <button
              className="outline small"
              onClick={() => handleOpenEdit(row.original)}
            >
              Edit
            </button>
            <button
              className="outline small"
              data-variant="danger"
              onClick={() => handleDelete(row.original)}
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
      <div className="table-toolbar">
        <h3>Roles</h3>
        <button className="outline small" onClick={handleOpenCreate}>
          New role
        </button>
      </div>

      {error && (
        <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
        {loading ? (
          <p className="empty-state">Loading…</p>
        ) : (
          <DataTable
            columns={columns}
            data={roles}
            emptyMessage="No roles yet. Add one to configure permissions."
          />
        )}
      </div>

      <Modal open={dialogOpen} onClose={handleCloseDialog}>
        <form onSubmit={handleSubmit}>
          <header>
            <h3>{editing ? `Edit role "${editing.name}"` : 'New role'}</h3>
            <p>
              {editing
                ? 'Update role configuration. Role name cannot be changed.'
                : 'Define a new RBAC role for this project.'}
            </p>
          </header>
          <div>
            {formError && (
              <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
                {formError}
              </div>
            )}
            <div className="field-grid">
              <label>
                Name
                <input
                  required
                  readOnly={editing !== null}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="editor"
                  pattern="^[a-z][a-z0-9_]*$"
                />
              </label>
              <label>
                Label
                <input
                  required
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Editor"
                />
              </label>
            </div>

            <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
              <label>
                <input
                  type="checkbox"
                  checked={isDefault}
                  onChange={(e) => setIsDefault(e.target.checked)}
                />{' '}
                Default
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={selfAssignable}
                  onChange={(e) => setSelfAssignable(e.target.checked)}
                />{' '}
                Self assignable
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={inviteOnly}
                  onChange={(e) => setInviteOnly(e.target.checked)}
                />{' '}
                Invite only
              </label>
            </div>

            <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
              <label>
                Inherits from
                <input
                  value={inheritsFrom}
                  onChange={(e) => setInheritsFrom(e.target.value)}
                  placeholder="viewer"
                />
              </label>
              <label>
                Position
                <input
                  type="number"
                  min={0}
                  value={position}
                  onChange={(e) => setPosition(e.target.value === '' ? '' : Number(e.target.value))}
                />
              </label>
            </div>
          </div>
          <footer>
            <button type="button" className="outline" onClick={handleCloseDialog}>
              Cancel
            </button>
            <button type="submit" disabled={submitting}>
              {submitting ? 'Saving…' : editing ? 'Save' : 'Create'}
            </button>
          </footer>
        </form>
      </Modal>
    </>
  )
}
