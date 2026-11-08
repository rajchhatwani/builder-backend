import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  AuthorizationModel,
  AuthorizationSettings,
  Entity,
  Policy,
  ProjectRole,
  RecommendAnswers,
  Recommendation,
  SpecForPolicies,
  ValidationIssue,
} from '../api/types'
import { CoverageTab } from './authz/CoverageTab'
import { PolicyEditor } from './authz/PolicyEditor'
import { SimulatorTab } from './authz/SimulatorTab'
import { buildCatalogue } from './authz/policyModel'
import { PermissionsPanel } from './PermissionsPanel'
import { RolesPanel } from './RolesPanel'
import { useUi } from './Ui'

type Tab = 'model' | 'roles' | 'permissions' | 'policies' | 'simulator' | 'coverage'

interface AuthorizationPanelProps {
  projectId: string
  entities: Entity[]
  roles: ProjectRole[]
  keycloak: boolean
  authEnabled: boolean
  onRolesChanged: () => void
  onChanged: () => void
}

const MODELS: { id: AuthorizationModel; title: string; help: string; fits: string }[] = [
  {
    id: 'rbac',
    title: 'Roles and permissions',
    help: 'Give each role a list of things it may do. Optionally limit a role to the records it owns or that belong to its organisation.',
    fits: 'Best for: a handful of roles, clear job titles, or any route that must work while signed out.',
  },
  {
    id: 'abac',
    title: 'Attribute rules (ABAC)',
    help: 'Rules that look at the person, the record and the moment: “the owner, while the status is draft, during office hours”.',
    fits: 'Best for: rules that depend on a record’s values, the time or the network. Every rule applies to everyone signed in.',
  },
  {
    id: 'pbac',
    title: 'Named policies per role (PBAC)',
    help: 'The same rules as ABAC, written as named policies that you attach to roles. Allow and deny, and a deny always wins.',
    fits: 'Best for: many roles with different rules, and reviewers who want to read the rulebook. “PBAC” has no single standard definition; this is ours.',
  },
]

const QUESTIONS: { key: keyof RecommendAnswers; label: string }[] = [
  { key: 'ownership_rules', label: 'People should only change records they created' },
  { key: 'tenant_rules', label: 'Several organisations share one deployment and must not see each other’s data' },
  { key: 'time_or_network_rules', label: 'Some actions are only allowed at certain times or from certain networks' },
  { key: 'per_record_rules', label: 'Rules depend on a record’s own values (status, amount, department…)' },
  { key: 'deny_rules', label: 'Some things must be impossible whatever else says yes (frozen or archived records)' },
  { key: 'audit_needs', label: 'Auditors or reviewers need to read the rules in plain language' },
  { key: 'public_routes', label: 'Some routes must work without signing in' },
]

function SubTabs({ tabs, value, onChange }: { tabs: { id: Tab; label: string }[]; value: Tab; onChange: (t: Tab) => void }) {
  return (
    <div className="tab-bar">
      {tabs.map((t) => (
        <button key={t.id} className="tab-btn" aria-selected={value === t.id} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

function Recommender({
  projectId,
  roleCount,
  current,
  onUse,
}: {
  projectId: string
  roleCount: number
  current: AuthorizationModel
  onUse: (m: AuthorizationModel) => void
}) {
  const [answers, setAnswers] = useState<RecommendAnswers>({
    roles: roleCount,
    ownership_rules: false,
    tenant_rules: false,
    time_or_network_rules: false,
    per_record_rules: false,
    deny_rules: false,
    audit_needs: false,
    policy_editors: 'developers',
    public_routes: false,
  })
  const [result, setResult] = useState<Recommendation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function ask(run: () => Promise<Recommendation>) {
    setBusy(true)
    setError(null)
    try {
      setResult(await run())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not get a recommendation.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ marginBlockStart: 'var(--space-4)' }}>
      <strong>Not sure which to pick?</strong>
      <p className="muted small-text">
        Answer a few questions. The suggestion is a fixed scoring table, not a guess, and it lists the reasons.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          ask(() => api.recommendAuthorization(projectId, answers))
        }}
      >
        <label style={{ maxWidth: '16rem' }}>
          How many roles will you have?
          <input
            type="number"
            min={0}
            max={100}
            value={answers.roles}
            onChange={(e) => setAnswers({ ...answers, roles: Number(e.target.value) })}
          />
        </label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', marginBlock: 'var(--space-3)' }}>
          {QUESTIONS.map((q) => (
            <label key={q.key} style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', margin: 0 }}>
              <input
                type="checkbox"
                checked={Boolean(answers[q.key])}
                onChange={(e) => setAnswers({ ...answers, [q.key]: e.target.checked })}
              />
              {q.label}
            </label>
          ))}
        </div>
        <label style={{ maxWidth: '24rem' }}>
          Who will change the rules later?
          <select
            value={answers.policy_editors}
            onChange={(e) => setAnswers({ ...answers, policy_editors: e.target.value as RecommendAnswers['policy_editors'] })}
          >
            <option value="developers">Developers</option>
            <option value="admins">Non-technical administrators</option>
          </select>
        </label>
        <div style={{ display: 'flex', gap: 'var(--space-2)', marginBlockStart: 'var(--space-3)' }}>
          <button type="submit" disabled={busy}>
            Recommend
          </button>
          <button type="button" className="outline" disabled={busy} onClick={() => ask(() => api.recommendFromProject(projectId))}>
            Read it from my project instead
          </button>
        </div>
      </form>
      {error && (
        <div role="alert" data-variant="danger" style={{ marginBlockStart: 'var(--space-3)' }}>
          {error}
        </div>
      )}
      {result && (
        <div role="status" className="card" style={{ marginBlockStart: 'var(--space-3)' }}>
          <strong>Suggested: {MODELS.find((m) => m.id === result.model)?.title}</strong>
          <ul>
            {result.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {result.cautions.length > 0 && (
            <>
              <p style={{ marginBlock: 'var(--space-2) var(--space-1)' }}>Keep in mind</p>
              <ul>
                {result.cautions.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </>
          )}
          <p className="muted small-text">Scores: {result.alternatives.concat([`${result.model} (score ${result.scores[result.model]})`]).join(' · ')}</p>
          {result.model !== current && (
            <button type="button" onClick={() => onUse(result.model)}>
              Use {MODELS.find((m) => m.id === result.model)?.title}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function AuthorizationPanel({
  projectId,
  entities,
  roles,
  keycloak,
  authEnabled,
  onRolesChanged,
  onChanged,
}: AuthorizationPanelProps) {
  const { confirm, toast } = useUi()
  const [settings, setSettings] = useState<AuthorizationSettings | null>(null)
  const [spec, setSpec] = useState<SpecForPolicies | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [tab, setTab] = useState<Tab>('model')
  const [error, setError] = useState<string | null>(null)

  // Roles are edited on the Roles tab; the parent's copy (used by permissions and the simulator) is refreshed on leaving it.
  useEffect(() => {
    if (tab !== 'roles') onRolesChanged()
  }, [tab])

  const refresh = useCallback(async () => {
    try {
      const [s, sp, iss] = await Promise.all([
        api.getAuthorization(projectId),
        api.getSpecForPolicies(projectId),
        api.authorizationIssues(projectId),
      ])
      setSettings(s)
      setSpec(sp)
      setIssues(iss.issues)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the authorization settings.')
    }
  }, [projectId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const catalogue = useMemo(() => (spec ? buildCatalogue(spec) : null), [spec])

  /** Saves the whole block. Returns an error message or null. */
  const save = useCallback(
    async (patch: Partial<{ model: AuthorizationModel; policies: Policy[]; attachments: Record<string, string[]> }>) => {
      if (!settings) return 'Not loaded yet.'
      try {
        const next = await api.putAuthorization(projectId, {
          model: patch.model ?? settings.model,
          policies: patch.policies ?? settings.policies,
          attachments: patch.attachments ?? settings.attachments,
          expected_version: settings.version,
        })
        setSettings(next)
        const [iss, sp] = await Promise.all([api.authorizationIssues(projectId), api.getSpecForPolicies(projectId)])
        setIssues(iss.issues)
        setSpec(sp)
        onChanged()
        return null
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          await refresh()
          return 'Someone else changed the authorization settings. They were reloaded: apply your change again.'
        }
        return err instanceof Error ? err.message : 'Could not save.'
      }
    },
    [settings, projectId, refresh, onChanged],
  )

  async function chooseModel(model: AuthorizationModel) {
    if (!settings || model === settings.model) return
    if (model === 'rbac' && settings.policies.length > 0) {
      const ok = await confirm({
        title: 'Go back to roles and permissions?',
        message: `Your ${settings.policies.length} polic${settings.policies.length === 1 ? 'y' : 'ies'} will be deleted. Export the spec first if you want a copy.`,
        confirmLabel: 'Switch and delete policies',
        danger: true,
      })
      if (!ok) return
      const message = await save({ model, policies: [], attachments: {} })
      if (message) setError(message)
      else toast('Using roles and permissions.')
      return
    }
    const message = await save({ model })
    if (message) {
      setError(message)
      return
    }
    setError(null)
    toast(model === 'rbac' ? 'Using roles and permissions.' : 'Switched. Add policies, because nothing is allowed until a policy allows it.')
    setTab(model === 'rbac' ? 'permissions' : 'policies')
  }

  if (error && !settings) {
    return (
      <div role="alert" data-variant="danger">
        {error}
      </div>
    )
  }
  if (!settings || !catalogue) return <p className="empty-state">Loading…</p>

  const policyModel = settings.model !== 'rbac'
  const tabs: { id: Tab; label: string }[] = [
    { id: 'model', label: 'Model' },
    { id: 'roles', label: 'Roles' },
    ...(policyModel
      ? ([
          { id: 'policies', label: 'Policies' },
          { id: 'simulator', label: 'Simulator' },
          { id: 'coverage', label: 'Coverage' },
        ] as { id: Tab; label: string }[])
      : ([{ id: 'permissions', label: 'Permissions' }] as { id: Tab; label: string }[])),
  ]
  const shown = tabs.some((t) => t.id === tab) ? tab : 'model'

  return (
    <>
      <SubTabs tabs={tabs} value={shown} onChange={setTab} />

      {!authEnabled && policyModel && (
        <div role="alert" data-variant="warning" style={{ marginBlockEnd: 'var(--space-4)' }}>
          {settings.model.toUpperCase()} decides what signed-in people may do, so turn on Authentication first.
        </div>
      )}
      {error && (
        <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
          {error}
        </div>
      )}
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
                  <small className="muted"> · {issue.path}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {shown === 'model' && (
        <>
          <div className="choice-grid">
            {MODELS.map((m) => (
              <label key={m.id} className="choice" data-selected={settings.model === m.id ? 'true' : undefined}>
                <input type="radio" name="authz-model" checked={settings.model === m.id} onChange={() => chooseModel(m.id)} />
                <strong>{m.title}</strong>
                <span className="muted">{m.help}</span>
                <span className="muted small-text">{m.fits}</span>
              </label>
            ))}
          </div>
          {policyModel && (
            <p className="muted small-text" style={{ marginBlockStart: 'var(--space-3)' }}>
              Under {settings.model.toUpperCase()} nothing is allowed unless a policy allows it, every operation needs sign-in, and routes
              cannot be public. Role permissions are not used: remove them or switch back to roles and permissions.
            </p>
          )}
          <Recommender projectId={projectId} roleCount={roles.length} current={settings.model} onUse={chooseModel} />
        </>
      )}

      {shown === 'roles' && <RolesPanel projectId={projectId} keycloak={keycloak} />}

      {shown === 'permissions' && (
        <PermissionsPanel projectId={projectId} entities={entities} roles={roles} keycloak={keycloak} />
      )}

      {shown === 'policies' && <PolicyEditor settings={settings} catalogue={catalogue} onSave={save} />}
      {shown === 'simulator' && <SimulatorTab projectId={projectId} catalogue={catalogue} />}
      {shown === 'coverage' && <CoverageTab projectId={projectId} version={settings.version} />}
    </>
  )
}
