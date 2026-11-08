import { useMemo, useState } from 'react'
import type { AuthorizationSettings, Policy } from '../../api/types'
import { Modal } from '../Modal'
import { useUi } from '../Ui'
import { ConditionEditor } from './ConditionEditor'
import { TEMPLATES, actionChoices, describe, emptyPolicy, prune, reachedEntities, type Catalogue } from './policyModel'

interface PolicyEditorProps {
  settings: AuthorizationSettings
  catalogue: Catalogue
  /** Saves the whole block; resolves to an error message, or null when it worked. */
  onSave: (next: { policies: Policy[]; attachments: Record<string, string[]> }) => Promise<string | null>
}

const ID_PATTERN = /^[a-z][a-z0-9_]{0,39}$/

function EffectBadge({ effect }: { effect: Policy['effect'] }) {
  return (
    <span className="badge" style={effect === 'deny' ? { background: 'var(--danger)', color: 'var(--danger-foreground, #fff)' } : undefined}>
      {effect}
    </span>
  )
}

export function PolicyEditor({ settings, catalogue, onSave }: PolicyEditorProps) {
  const { confirm, toast } = useUi()
  const [editing, setEditing] = useState<Policy | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const pbac = settings.model === 'pbac'
  const choices = useMemo(() => actionChoices(catalogue), [catalogue])
  const principals = useMemo(() => ['*', ...catalogue.roles], [catalogue.roles])

  function carriers(policyId: string): string[] {
    if (!pbac) return ['everyone signed in']
    return Object.entries(settings.attachments)
      .filter(([, ids]) => ids.includes(policyId))
      .map(([who]) => (who === '*' ? 'everyone signed in' : `role ${who}`))
  }

  function open(policy: Policy, fresh: boolean) {
    setEditing(structuredClone(policy))
    setIsNew(fresh)
    setFormError(null)
  }

  async function persist(policies: Policy[], attachments: Record<string, string[]>): Promise<boolean> {
    setSaving(true)
    const message = await onSave({ policies, attachments })
    setSaving(false)
    if (message) {
      setError(message)
      return false
    }
    setError(null)
    return true
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!editing) return
    if (!ID_PATTERN.test(editing.id)) {
      setFormError('The name needs lowercase letters, digits and underscores, starting with a letter.')
      return
    }
    if (isNew && settings.policies.some((p) => p.id === editing.id)) {
      setFormError('A policy with this name already exists.')
      return
    }
    if (editing.actions.length === 0) {
      setFormError('Choose at least one action the policy is about.')
      return
    }
    const policy: Policy = { ...editing, when: prune(editing.when) }
    const policies = isNew
      ? [...settings.policies, policy]
      : settings.policies.map((p) => (p.id === policy.id ? policy : p))
    let attachments = settings.attachments
    if (isNew && pbac) {
      // A new policy starts attached to nobody: say so rather than silently granting it.
      attachments = { ...attachments }
    }
    if (await persist(policies, attachments)) {
      setEditing(null)
      toast(pbac && isNew ? 'Policy saved. Attach it to a role below so it takes effect.' : 'Policy saved.')
    } else {
      setFormError('The server refused the change. See the message above the list.')
    }
  }

  async function remove(policy: Policy) {
    const ok = await confirm({
      title: `Delete policy "${policy.id}"?`,
      message: 'Operations it allowed may become unreachable. The coverage matrix shows what changes.',
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    const attachments = Object.fromEntries(
      Object.entries(settings.attachments).map(([who, ids]) => [who, ids.filter((id) => id !== policy.id)]),
    )
    await persist(
      settings.policies.filter((p) => p.id !== policy.id),
      attachments,
    )
  }

  async function toggleAttachment(who: string, policyId: string, on: boolean) {
    const current = settings.attachments[who] ?? []
    const next = on ? [...new Set([...current, policyId])] : current.filter((id) => id !== policyId)
    const attachments = { ...settings.attachments, [who]: next }
    if (next.length === 0) delete attachments[who]
    await persist(settings.policies, attachments)
  }

  const entityHint = catalogue.entities[0]?.name ?? 'Item'

  return (
    <div>
      {error && (
        <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
          {error}
        </div>
      )}

      <div className="card" style={{ marginBlockEnd: 'var(--space-4)' }}>
        <div className="table-toolbar">
          <div>
            <strong>Policies</strong>
            <p className="muted small-text" style={{ margin: 0 }}>
              Nothing is allowed unless a policy allows it, and a matching deny policy always wins.
            </p>
          </div>
          <button type="button" onClick={() => open(emptyPolicy(settings.policies), true)}>
            New policy
          </button>
        </div>

        {settings.policies.length === 0 ? (
          <p className="empty-state">
            No policies yet, so nobody can do anything. Start from a template:
            <span style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'center', flexWrap: 'wrap', marginBlockStart: 'var(--space-3)' }}>
              {TEMPLATES.map((t) => (
                <button
                  key={t.title}
                  type="button"
                  className="outline small"
                  title={t.help}
                  onClick={() => {
                    const base = emptyPolicy(settings.policies)
                    open({ ...base, ...t.build(entityHint) }, true)
                  }}
                >
                  {t.title}
                </button>
              ))}
            </span>
          </p>
        ) : (
          <ul className="relation-list">
            {settings.policies.map((p) => (
              <li key={p.id} style={{ alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
                    <strong>{p.id}</strong>
                    <EffectBadge effect={p.effect} />
                    {p.actions.map((a) => (
                      <span key={a} className="badge badge-outline">
                        {a}
                      </span>
                    ))}
                  </div>
                  {p.description && <p style={{ margin: 'var(--space-1) 0' }}>{p.description}</p>}
                  <p className="muted small-text" style={{ margin: 0 }}>
                    When: {describe(p.when)}
                  </p>
                  <p className="muted small-text" style={{ margin: 0 }}>
                    Applies to: {carriers(p.id).join(', ') || 'nobody (not attached to a role yet)'}
                  </p>
                </div>
                <div className="row-actions">
                  <button type="button" className="outline small" onClick={() => open(p, false)}>
                    Edit
                  </button>
                  <button type="button" className="outline small" onClick={() => remove(p)}>
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {pbac && settings.policies.length > 0 && (
        <div className="card">
          <strong>Who carries which policy</strong>
          <p className="muted small-text">
            A policy only applies to people who hold a role it is attached to. “Everyone signed in” covers all roles.
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table className="permission-matrix">
              <thead>
                <tr>
                  <th>Policy</th>
                  {principals.map((who) => (
                    <th key={who}>{who === '*' ? 'Everyone signed in' : who}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {settings.policies.map((p) => (
                  <tr key={p.id}>
                    <td className="entity-name">
                      {p.id} <EffectBadge effect={p.effect} />
                    </td>
                    {principals.map((who) => (
                      <td key={who}>
                        <input
                          type="checkbox"
                          aria-label={`${p.id} for ${who === '*' ? 'everyone' : who}`}
                          disabled={saving}
                          checked={(settings.attachments[who] ?? []).includes(p.id)}
                          onChange={(e) => toggleAttachment(who, p.id, e.target.checked)}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal open={editing !== null} onClose={() => setEditing(null)}>
        {editing && (
          <form onSubmit={submit} method="dialog" className="policy-form">
            <header>
              <h3>{isNew ? 'New policy' : `Edit policy “${editing.id}”`}</h3>
              <p>What is allowed or denied, to which actions, and under which conditions.</p>
            </header>
            <div>
              {formError && (
                <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-3)' }}>
                  {formError}
                </div>
              )}
              <div className="field-grid">
                <label>
                  Name
                  <input
                    value={editing.id}
                    disabled={!isNew}
                    onChange={(e) => setEditing({ ...editing, id: e.target.value })}
                    placeholder="own_records"
                  />
                </label>
                <fieldset style={{ border: 0, padding: 0 }}>
                  <legend>Effect</legend>
                  <label style={{ display: 'inline-flex', gap: 'var(--space-1)', marginInlineEnd: 'var(--space-4)' }}>
                    <input type="radio" checked={editing.effect === 'allow'} onChange={() => setEditing({ ...editing, effect: 'allow' })} />
                    Allow
                  </label>
                  <label style={{ display: 'inline-flex', gap: 'var(--space-1)' }}>
                    <input type="radio" checked={editing.effect === 'deny'} onChange={() => setEditing({ ...editing, effect: 'deny' })} />
                    Deny (always wins)
                  </label>
                </fieldset>
              </div>
              <label style={{ marginBlockStart: 'var(--space-3)' }}>
                Description (shown in the generated documentation)
                <input
                  value={editing.description}
                  maxLength={300}
                  onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                />
              </label>

              <fieldset style={{ border: 0, padding: 0, marginBlockStart: 'var(--space-3)' }}>
                <legend>Actions this policy is about</legend>
                <div
                  style={{
                    maxHeight: '11rem',
                    overflowY: 'auto',
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(11rem, 1fr))',
                    gap: 'var(--space-1)',
                    padding: 'var(--space-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                  }}
                >
                  {choices.map((a) => (
                    <label key={a} style={{ display: 'flex', gap: 'var(--space-1)', margin: 0 }}>
                      <input
                        type="checkbox"
                        checked={editing.actions.includes(a)}
                        onChange={(e) =>
                          setEditing({
                            ...editing,
                            actions: e.target.checked ? [...editing.actions, a] : editing.actions.filter((x) => x !== a),
                          })
                        }
                      />
                      {a === '*' ? 'Everything' : a}
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset style={{ border: 0, padding: 0, marginBlockStart: 'var(--space-3)' }}>
                <legend>Only when</legend>
                <ConditionEditor
                  value={editing.when}
                  onChange={(when) => setEditing({ ...editing, when })}
                  catalogue={catalogue}
                  entities={reachedEntities(catalogue, editing.actions)}
                />
                <p className="muted small-text">Reads as: {describe(prune(editing.when))}</p>
              </fieldset>
            </div>
            <footer>
              <button type="button" className="outline" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="submit" disabled={saving}>
                {saving ? 'Saving…' : 'Save policy'}
              </button>
            </footer>
          </form>
        )}
      </Modal>
    </div>
  )
}
