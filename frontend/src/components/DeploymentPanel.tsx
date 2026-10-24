import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DeploymentPlan, DeploymentSettings, DeployEnvironment, ValidationIssue } from '../api/types'
import { useUi } from './Ui'

const CLOUDS: { id: string; title: string; help: string; region: string }[] = [
  {
    id: 'aws',
    title: 'Amazon Web Services',
    help: 'ECS Fargate behind a load balancer with a web firewall, RDS PostgreSQL in private subnets.',
    region: 'eu-west-1',
  },
  {
    id: 'azure',
    title: 'Microsoft Azure',
    help: 'Container Apps with managed HTTPS, PostgreSQL Flexible Server on a private network.',
    region: 'westeurope',
  },
  {
    id: 'gcp',
    title: 'Google Cloud',
    help: 'Cloud Run with managed HTTPS, Cloud SQL with a private IP.',
    region: 'europe-west1',
  },
]

const PROFILES = [
  { id: 'small', label: 'Small', help: 'a few users; one small instance' },
  { id: 'medium', label: 'Medium', help: 'steady traffic; 2 to 6 instances, standby database' },
  { id: 'large', label: 'Large', help: 'heavy traffic; 3 to 20 larger instances' },
]

const SETUP: Record<string, { identity: string; command: string }> = {
  aws: {
    identity: 'an IAM role per environment that only this repository can assume (GitHub OIDC)',
    command: 'cd deploy/aws/bootstrap && terraform init && terraform apply',
  },
  azure: {
    identity: 'an Entra application per environment with a federated credential (no client secret)',
    command: 'cd deploy/azure/bootstrap && terraform init && terraform apply -var subscription_id=<id>',
  },
  gcp: {
    identity: 'a service account per environment behind Workload Identity Federation (no key)',
    command: 'cd deploy/gcp/bootstrap && terraform init && terraform apply -var project_id=<id>',
  },
}

const num = (text: string): number | null => (text.trim() === '' ? null : Number(text))

function EnvironmentCard({
  env,
  onChange,
  onRemove,
  canRemove,
  tfvars,
}: {
  env: DeployEnvironment
  onChange: (e: DeployEnvironment) => void
  onRemove: () => void
  canRemove: boolean
  tfvars: string | undefined
}) {
  const set = <K extends keyof DeployEnvironment>(key: K, value: DeployEnvironment[K]) => onChange({ ...env, [key]: value })
  return (
    <div className="idp-card">
      <div className="idp-card-head">
        <strong>{env.name || 'new environment'}</strong>
        {canRemove && (
          <button type="button" className="outline small" onClick={onRemove}>
            Remove
          </button>
        )}
      </div>
      <div className="field-grid">
        <label>
          Name
          <input value={env.name} onChange={(e) => set('name', e.target.value.toLowerCase())} placeholder="staging" />
        </label>
        <label>
          Size
          <select value={env.profile} onChange={(e) => set('profile', e.target.value)}>
            {PROFILES.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}: {p.help}
              </option>
            ))}
          </select>
        </label>
      </div>
      <details style={{ marginBlockStart: 'var(--space-3)' }}>
        <summary>Fine-tune (leave empty to use the size above)</summary>
        <div className="field-grid" style={{ marginBlockStart: 'var(--space-2)' }}>
          <label>
            Fewest instances
            <input type="number" min={0} value={env.min_instances ?? ''} onChange={(e) => set('min_instances', num(e.target.value))} />
          </label>
          <label>
            Most instances
            <input type="number" min={1} value={env.max_instances ?? ''} onChange={(e) => set('max_instances', num(e.target.value))} />
          </label>
          <label>
            CPU (millicores)
            <input type="number" value={env.cpu ?? ''} onChange={(e) => set('cpu', num(e.target.value))} />
          </label>
          <label>
            Memory (MB)
            <input type="number" value={env.memory ?? ''} onChange={(e) => set('memory', num(e.target.value))} />
          </label>
          <label>
            Database storage (GB)
            <input type="number" min={10} value={env.db_storage_gb ?? ''} onChange={(e) => set('db_storage_gb', num(e.target.value))} />
          </label>
        </div>
        <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', marginBlockStart: 'var(--space-2)' }}>
          <input
            type="checkbox"
            checked={env.db_high_availability ?? env.profile !== 'small'}
            onChange={(e) => set('db_high_availability', e.target.checked)}
          />
          Standby database in a second zone
        </label>
        <label style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={env.deletion_protection ?? env.name === 'prod'}
            onChange={(e) => set('deletion_protection', e.target.checked)}
          />
          Protect against deletion (database, load balancer), keep a final backup
        </label>
      </details>
      {tfvars && (
        <details style={{ marginBlockStart: 'var(--space-2)' }}>
          <summary>
            <code>environments/{env.name}.tfvars</code> (what you will get)
          </summary>
          <pre style={{ overflowX: 'auto', fontSize: 'var(--text-8)' }}>{tfvars}</pre>
        </details>
      )}
    </div>
  )
}

/** CI/CD workflows and Terraform for AWS, Azure or Google Cloud, with the one-time trust setup. */
export function DeploymentPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const { toast } = useUi()
  const [settings, setSettings] = useState<DeploymentSettings | null>(null)
  const [form, setForm] = useState<DeploymentSettings | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [plan, setPlan] = useState<DeploymentPlan | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const planSeq = useRef(0)

  const load = useCallback(async () => {
    try {
      const [s, i] = await Promise.all([api.getDeployment(projectId), api.deploymentIssues(projectId)])
      setSettings(s)
      // A fresh project has no region yet: start from the usual one of the chosen cloud.
      setForm({ ...s, region: s.region || CLOUDS.find((c) => c.id === s.cloud)?.region || '' })
      setIssues(i.issues)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the deployment settings.')
    }
  }, [projectId])

  useEffect(() => {
    load()
  }, [load])

  // Live preview: ask the server what the current (unsaved) form turns into.
  useEffect(() => {
    if (!form) return
    const seq = ++planSeq.current
    const timer = setTimeout(() => {
      api
        .deploymentPlan(projectId, {
          enabled: form.enabled,
          cloud: form.cloud,
          region: form.region,
          github_repo: form.github_repo,
          environments: form.environments,
        })
        .then((p) => {
          if (seq === planSeq.current) setPlan(p)
        })
        .catch(() => {
          if (seq === planSeq.current) setPlan(null)
        })
    }, 300)
    return () => clearTimeout(timer)
  }, [form, projectId])

  if (error && !settings) {
    return (
      <div role="alert" data-variant="danger">
        {error}
      </div>
    )
  }
  if (!settings || !form) return <p className="empty-state">Loading…</p>

  const setField = <K extends keyof DeploymentSettings>(key: K, value: DeploymentSettings[K]) => setForm({ ...form, [key]: value })
  const cloud = CLOUDS.find((c) => c.id === form.cloud) ?? CLOUDS[0]
  const never = settings.version === 0

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!form || !settings) return
    setSaving(true)
    setError(null)
    try {
      const saved = await api.putDeployment(projectId, {
        enabled: form.enabled,
        cloud: form.cloud,
        region: form.region,
        github_repo: form.github_repo.trim(),
        environments: form.environments,
        expected_version: settings.version,
      })
      setSettings(saved)
      setForm(saved)
      setIssues((await api.deploymentIssues(projectId)).issues)
      onChanged()
      toast('Deployment settings saved.')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        await load()
        setError('Someone else changed these settings. They were reloaded: apply your change again.')
      } else {
        setError(err instanceof Error ? err.message : 'Could not save.')
      }
    } finally {
      setSaving(false)
    }
  }

  function pickCloud(id: string) {
    const next = CLOUDS.find((c) => c.id === id) ?? CLOUDS[0]
    // The region of another cloud is never valid: offer the new cloud's usual one.
    setForm({ ...form!, cloud: id, region: CLOUDS.some((c) => c.region === form!.region) || form!.region === '' ? next.region : form!.region })
  }

  return (
    <>
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
                  <small className="muted"> · {issue.path.replace('deployment.', '')}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form className="card" onSubmit={save}>
        {error && (
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-4)' }}>
            {error}
          </div>
        )}
        <div className="toggle-field">
          <label>
            <input type="checkbox" checked={form.enabled} onChange={(e) => setField('enabled', e.target.checked)} />
            <span>
              <strong>Generate CI/CD pipelines and cloud infrastructure</strong>
              <br />
              <span className="muted small-text">
                {never
                  ? 'Off until you save. The next download then includes GitHub Actions workflows and Terraform.'
                  : 'Turn off to stop generating them. Nothing already deployed is changed.'}
              </span>
            </span>
          </label>
        </div>

        <details open className="auth-section">
          <summary>Where</summary>
          <div className="auth-section-body">
            <div className="choice-grid">
              {CLOUDS.map((c) => (
                <label key={c.id} className="choice" data-selected={form.cloud === c.id ? 'true' : undefined}>
                  <input type="radio" name="cloud" checked={form.cloud === c.id} onChange={() => pickCloud(c.id)} />
                  <strong>{c.title}</strong>
                  <span className="muted">{c.help}</span>
                </label>
              ))}
            </div>
            <div className="field-grid" style={{ marginBlockStart: 'var(--space-4)' }}>
              <label>
                Region
                <input value={form.region} placeholder={cloud.region} onChange={(e) => setField('region', e.target.value.trim())} />
              </label>
              <label>
                GitHub repository (owner/name)
                <input value={form.github_repo} placeholder="acme/my-backend" onChange={(e) => setField('github_repo', e.target.value)} />
              </label>
            </div>
            <p className="muted small-text">
              Only this repository can deploy: the cloud trusts GitHub’s short-lived sign-in token for exactly this repository and the
              environment a job runs in. No cloud key, password or token is stored here or written into your project.
            </p>
            {plan && plan.notes.length > 0 && (
              <ul className="small-text muted">
                {plan.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            )}
          </div>
        </details>

        <details open className="auth-section">
          <summary>Environments</summary>
          <div className="auth-section-body">
            <p className="muted small-text">
              Each environment is its own copy of the infrastructure. A push to <code>main</code> deploys the first one; promoting to the
              others is a button in GitHub, with required reviewers for production.
            </p>
            {form.environments.map((env, i) => (
              <EnvironmentCard
                key={i}
                env={env}
                canRemove={form.environments.length > 1}
                tfvars={plan?.environments.find((e) => e.name === env.name)?.tfvars}
                onChange={(next) => setField('environments', form.environments.map((e, j) => (j === i ? next : e)))}
                onRemove={() => setField('environments', form.environments.filter((_, j) => j !== i))}
              />
            ))}
            <button
              type="button"
              className="outline small"
              onClick={() => setField('environments', [...form.environments, { name: '', profile: 'small' } as DeployEnvironment])}
            >
              + Add an environment
            </button>
            {plan && plan.valid_sizes.length > 0 && (
              <p className="muted small-text" style={{ marginBlockStart: 'var(--space-3)' }}>
                Sizes {cloud.title} offers (CPU millicores / memory MB): {plan.valid_sizes.map(([c, m]) => `${c}/${m}`).join(', ')}.
              </p>
            )}
          </div>
        </details>

        <div style={{ marginBlockStart: 'var(--space-4)' }}>
          <button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>

      <div className="card" style={{ marginBlockStart: 'var(--space-4)' }}>
        <strong>One-time setup after you download</strong>
        <ol>
          <li>
            Run the bootstrap once with your own cloud sign-in: <code>{SETUP[form.cloud]?.command}</code>. It creates the state storage, the
            image registry and {SETUP[form.cloud]?.identity}.
          </li>
          <li>
            In GitHub create one environment per name above and add required reviewers to production. Set the variables the bootstrap prints
            (listed in <code>docs/DEPLOYMENT.md</code>).
          </li>
          <li>Fill in the application’s secrets in the cloud’s secret manager. The pipeline creates the empty secrets and stops until you do.</li>
          <li>Push to <code>main</code>: the pipeline builds, scans, signs, migrates, deploys and smoke-tests.</li>
        </ol>
        <p className="muted small-text">
          Not supported yet (the dashboard refuses to enable deployment with them): payments, file uploads with malware scanning, Redis
          token storage and a Keycloak server of its own. The Terraform is validated with the real provider schemas but has not been applied to a
          real account by the builder: use the first environment as the rehearsal.
        </p>
      </div>
    </>
  )
}
