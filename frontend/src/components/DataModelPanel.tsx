import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Entity, Relation } from '../api/types'
import { EntityDetail } from './EntityDetail'
import { NewEntityDialog } from './NewEntityDialog'
import { NewRelationDialog } from './NewRelationDialog'
import { useUi } from './Ui'

interface DataModelPanelProps {
  projectId: string
  entities: Entity[]
  relations: Relation[]
  loading: boolean
  onChanged: () => void
}

const KIND_WORDS: Record<Relation['kind'], string> = {
  one_to_many: 'has many',
  many_to_many: 'has and belongs to many',
  one_to_one: 'has one',
}

/** Entities on the left, the selected entity's fields, options and relations on the right. */
export function DataModelPanel({ projectId, entities, relations, loading, onChanged }: DataModelPanelProps) {
  const { confirm, toast } = useUi()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [entityDialogOpen, setEntityDialogOpen] = useState(false)
  const [relationDialogOpen, setRelationDialogOpen] = useState(false)

  // Keep a valid selection: first entity by default, and after the selected one is deleted.
  useEffect(() => {
    if (entities.length === 0) setSelectedId(null)
    else if (!entities.some((e) => e.id === selectedId)) setSelectedId(entities[0].id)
  }, [entities, selectedId])

  const selected = entities.find((e) => e.id === selectedId)
  const nameById = new Map(entities.map((e) => [e.id, e.name]))
  const relatedToSelected = relations.filter(
    (r) => r.from_entity_id === selectedId || r.to_entity_id === selectedId,
  )

  async function deleteEntity(entity: Entity) {
    const ok = await confirm({
      title: `Delete "${entity.name}"?`,
      message: 'Its fields and relations are removed too.',
      confirmLabel: 'Delete entity',
      danger: true,
    })
    if (!ok) return
    await api.deleteEntity(entity.id)
    toast(`Deleted "${entity.name}".`)
    onChanged()
  }

  async function deleteRelation(relation: Relation) {
    const ok = await confirm({ title: 'Remove this relation?', confirmLabel: 'Remove', danger: true })
    if (!ok) return
    await api.deleteRelation(relation.id)
    onChanged()
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Data model</h1>
          <p>The things your backend stores, such as posts, customers or orders, and how they connect.</p>
        </div>
      </div>

      {loading && entities.length === 0 ? (
        <p className="empty-state">Loading…</p>
      ) : entities.length === 0 ? (
        <div className="card empty-hero">
          <h2>Add your first entity</h2>
          <p>An entity is one kind of record, for example a Post with a title and a body.</p>
          <button onClick={() => setEntityDialogOpen(true)}>New entity</button>
        </div>
      ) : (
        <div className="master-detail">
          <div className="master-list card">
            <div className="table-toolbar">
              <strong>Entities</strong>
              <button className="small" onClick={() => setEntityDialogOpen(true)}>
                New
              </button>
            </div>
            <ul className="entity-list">
              {entities.map((entity) => (
                <li key={entity.id}>
                  <button
                    className="entity-item"
                    aria-current={entity.id === selectedId ? 'true' : undefined}
                    onClick={() => setSelectedId(entity.id)}
                  >
                    <span>{entity.name}</span>
                    <small className="muted">/{entity.plural_path}</small>
                  </button>
                </li>
              ))}
            </ul>
            <div className="table-toolbar">
              <strong>Relations</strong>
              <button
                className="outline small"
                disabled={entities.length < 2}
                title={entities.length < 2 ? 'Add a second entity first' : undefined}
                onClick={() => setRelationDialogOpen(true)}
              >
                New
              </button>
            </div>
            {relations.length === 0 ? (
              <p className="muted small-text">Connect two entities, e.g. a Post has many Comments.</p>
            ) : (
              <p className="muted small-text">{relations.length} in this project.</p>
            )}
          </div>

          <div className="detail-pane">
            {selected && (
              <>
                <EntityDetail key={selected.id} entity={selected} onChanged={onChanged} />

                <div className="table-toolbar">
                  <h3>Relations of {selected.name}</h3>
                </div>
                <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
                  {relatedToSelected.length === 0 ? (
                    <p className="empty-state">No relations yet.</p>
                  ) : (
                    <ul className="relation-list">
                      {relatedToSelected.map((r) => (
                        <li key={r.id}>
                          <span>
                            <strong>{nameById.get(r.from_entity_id) ?? '?'}</strong> {KIND_WORDS[r.kind]}{' '}
                            <strong>{nameById.get(r.to_entity_id) ?? '?'}</strong>
                            <small className="muted">
                              {' '}
                              · as <code>{r.from_name}</code> / <code>{r.to_name}</code> · on delete {r.on_delete.replace('_', ' ')}
                            </small>
                          </span>
                          <button className="ghost small" data-variant="danger" onClick={() => deleteRelation(r)}>
                            Remove
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <button className="ghost small" data-variant="danger" onClick={() => deleteEntity(selected)}>
                  Delete entity “{selected.name}”
                </button>
              </>
            )}
          </div>
        </div>
      )}

      <NewEntityDialog
        open={entityDialogOpen}
        projectId={projectId}
        onClose={() => setEntityDialogOpen(false)}
        onCreated={(entity) => {
          setEntityDialogOpen(false)
          setSelectedId(entity.id)
          onChanged()
        }}
      />

      <NewRelationDialog
        open={relationDialogOpen}
        projectId={projectId}
        entities={entities}
        onClose={() => setRelationDialogOpen(false)}
        onCreated={() => {
          setRelationDialogOpen(false)
          onChanged()
        }}
      />
    </>
  )
}
