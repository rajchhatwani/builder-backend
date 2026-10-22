import { useState, useEffect, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Entity, ProjectRole, ProjectPermission, AuthOperation, RowRule, PermissionEntry } from '../api/types'
import { Modal } from './Modal'

const AUTH_OPERATIONS: AuthOperation[] = ['list', 'get', 'create', 'replace', 'update', 'delete', 'head']

interface PermissionsPanelProps {
  projectId: string
  entities: Entity[] // already loaded by the parent
  roles: ProjectRole[] // already loaded by the parent
}

export function PermissionsPanel({ projectId, entities, roles }: PermissionsPanelProps) {
  const [permissions, setPermissions] = useState<Record<string, PermissionEntry>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Editor Modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [editingEntity, setEditingEntity] = useState<Entity | null>(null)
  const [editingOperation, setEditingOperation] = useState<AuthOperation | null>(null)
  const [formRoles, setFormRoles] = useState<string[]>([])
  const [formRowRule, setFormRowRule] = useState<RowRule | 'none'>('none')
  const [formFilterField, setFormFilterField] = useState('')
  const [formFilterValue, setFormFilterValue] = useState('')
  const [modalError, setModalError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    api
      .listPermissions(projectId, 500, 0)
      .then((res) => {
        if (cancelled) return
        const map: Record<string, PermissionEntry> = {}
        for (const p of res.items as ProjectPermission[]) {
          const key = `${p.entity_id}:${p.operation}`
          map[key] = {
            entity_id: p.entity_id,
            operation: p.operation,
            roles: p.roles ?? [],
            row_rule: p.row_rule ?? null,
            custom_filter_field: p.custom_filter_field ?? null,
            custom_filter_value: p.custom_filter_value ?? null,
          }
        }
        setPermissions(map)
        setLoading(false)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Failed to load permissions.')
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [projectId, entities])

  function openEditor(entity: Entity, operation: AuthOperation) {
    const key = `${entity.id}:${operation}`
    const entry = permissions[key]

    setEditingEntity(entity)
    setEditingOperation(operation)
    setFormRoles(entry?.roles ? [...entry.roles] : [])
    setFormRowRule(entry?.row_rule ?? 'none')
    setFormFilterField(entry?.custom_filter_field ?? '')
    setFormFilterValue(entry?.custom_filter_value ?? '')
    setModalError(null)
    setModalOpen(true)
  }

  function closeEditor() {
    setModalOpen(false)
    setEditingEntity(null)
    setEditingOperation(null)
    setModalError(null)
  }

  function handleEditorSubmit(event: FormEvent) {
    event.preventDefault()
    if (!editingEntity || !editingOperation) return

    if (formRowRule === 'custom_filter') {
      if (!formFilterField.trim()) {
        setModalError('Filter field is required when using custom_filter.')
        return
      }
      if (!formFilterValue.trim()) {
        setModalError('Filter value is required when using custom_filter.')
        return
      }
    }

    const key = `${editingEntity.id}:${editingOperation}`
    const updatedEntry: PermissionEntry = {
      entity_id: editingEntity.id,
      operation: editingOperation,
      roles: formRoles,
      row_rule: formRowRule === 'none' ? null : formRowRule,
      custom_filter_field: formRowRule === 'custom_filter' ? formFilterField.trim() : null,
      custom_filter_value: formRowRule === 'custom_filter' ? formFilterValue.trim() : null,
    }

    setPermissions((prev) => ({
      ...prev,
      [key]: updatedEntry,
    }))

    closeEditor()
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    setSuccess(null)

    const entries: PermissionEntry[] = Object.values(permissions).filter(
      (entry) => (entry.roles && entry.roles.length > 0) || Boolean(entry.row_rule),
    )

    if (entries.length === 0) {
      setError('No permissions configured to save. Assign at least one role or row rule first.')
      setSaving(false)
      return
    }

    try {
      const updated = await api.bulkUpsertPermissions(projectId, entries)
      const map: Record<string, PermissionEntry> = {}
      for (const p of updated) {
        const key = `${p.entity_id}:${p.operation}`
        map[key] = {
          entity_id: p.entity_id,
          operation: p.operation,
          roles: p.roles ?? [],
          row_rule: p.row_rule ?? null,
          custom_filter_field: p.custom_filter_field ?? null,
          custom_filter_value: p.custom_filter_value ?? null,
        }
      }
      setPermissions(map)
      setSuccess('Permissions saved successfully.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save permissions.')
    } finally {
      setSaving(false)
    }
  }

  if (entities.length === 0) {
    return (
      <div className="card">
        <p className="empty-state">No entities exist yet. Create an entity first to configure permissions.</p>
      </div>
    )
  }

  return (
    <>
      <div className="table-toolbar">
        <h3>Permissions</h3>
        <button disabled={saving || loading} onClick={handleSave}>
          {saving ? 'Saving…' : 'Save all'}
        </button>
      </div>

      {error && (
        <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
          {error}
        </div>
      )}

      {success && (
        <div role="alert" data-variant="success" style={{ marginBlockEnd: 'var(--space-4)' }}>
          {success}
        </div>
      )}

      <div className="card">
        {loading ? (
          <p className="empty-state">Loading permissions…</p>
        ) : (
          <table className="permission-matrix">
            <thead>
              <tr>
                <th>Entity</th>
                {AUTH_OPERATIONS.map((op) => (
                  <th key={op}>{op}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entities.map((entity) => (
                <tr key={entity.id}>
                  <td className="entity-name">{entity.name}</td>
                  {AUTH_OPERATIONS.map((op) => {
                    const entry = permissions[`${entity.id}:${op}`]
                    const assignedRoles = entry?.roles ?? []
                    const hasRoles = assignedRoles.length > 0
                    const hasRowRule = Boolean(entry?.row_rule)

                    return (
                      <td
                        key={op}
                        className="matrix-cell"
                        onClick={() => openEditor(entity, op)}
                        title={`Click to edit permissions for ${entity.name}:${op}`}
                      >
                        {hasRoles ? (
                          assignedRoles.map((roleName) => (
                            <span key={roleName} className="badge">
                              {roleName}
                            </span>
                          ))
                        ) : (
                          <span style={{ color: 'var(--muted-foreground)' }}>—</span>
                        )}
                        {hasRowRule && (
                          <span className="badge badge-outline">
                            {entry?.row_rule}
                          </span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBlockStart: 'var(--space-4)' }}>
        <button disabled={saving || loading} onClick={handleSave}>
          {saving ? 'Saving…' : 'Save all permissions'}
        </button>
      </div>

      <Modal open={modalOpen} onClose={closeEditor}>
        {editingEntity && editingOperation && (
          <form onSubmit={handleEditorSubmit}>
            <header>
              <h3>
                {editingEntity.name} &middot; {editingOperation}
              </h3>
              <p>Configure role-based access control and row filtering.</p>
            </header>

            <div>
              {modalError && (
                <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
                  {modalError}
                </div>
              )}

              <div style={{ marginBlockEnd: 'var(--space-4)' }}>
                <label style={{ fontWeight: 'var(--font-medium)', marginBlockEnd: 'var(--space-2)', display: 'block' }}>
                  Roles
                </label>
                {roles.length === 0 ? (
                  <p style={{ color: 'var(--muted-foreground)', fontSize: 'var(--text-7)' }}>
                    No roles defined for this project.
                  </p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                    {roles.map((role) => (
                      <label
                        key={role.name}
                        style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', margin: 0 }}
                      >
                        <input
                          type="checkbox"
                          checked={formRoles.includes(role.name)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setFormRoles((prev) => [...prev, role.name])
                            } else {
                              setFormRoles((prev) => prev.filter((r) => r !== role.name))
                            }
                          }}
                        />
                        <span>{role.name}</span>
                        {role.label && role.label !== role.name && (
                          <span style={{ color: 'var(--muted-foreground)', fontSize: 'var(--text-7)' }}>
                            ({role.label})
                          </span>
                        )}
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <label style={{ marginBlockEnd: 'var(--space-4)', display: 'block' }}>
                Row rule
                <select
                  value={formRowRule}
                  onChange={(e) => {
                    setFormRowRule(e.target.value as RowRule | 'none')
                    setModalError(null)
                  }}
                >
                  <option value="none">none</option>
                  <option value="owner">owner</option>
                  <option value="role_scoped">role_scoped</option>
                  <option value="tenant">tenant</option>
                  <option value="custom_filter">custom_filter</option>
                </select>
              </label>

              {formRowRule === 'custom_filter' && (
                <div className="field-grid" style={{ marginBlockEnd: 'var(--space-4)' }}>
                  <label>
                    Custom filter field
                    <input
                      required
                      value={formFilterField}
                      onChange={(e) => setFormFilterField(e.target.value)}
                      placeholder="e.g. author_id"
                    />
                  </label>
                  <label>
                    Custom filter value
                    <input
                      required
                      value={formFilterValue}
                      onChange={(e) => setFormFilterValue(e.target.value)}
                      placeholder="e.g. current_user.id"
                    />
                  </label>
                </div>
              )}
            </div>

            <footer>
              <button type="button" className="outline" onClick={closeEditor}>
                Cancel
              </button>
              <button type="submit">
                Save
              </button>
            </footer>
          </form>
        )}
      </Modal>
    </>
  )
}

export default PermissionsPanel
