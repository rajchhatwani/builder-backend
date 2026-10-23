import type { ReactNode } from 'react'
import type { ValidationIssue } from '../api/types'
import { link, type Section } from './Sidebar'

interface OverviewPanelProps {
  projectId: string
  entityCount: number
  authEnabled: boolean
  /** True when Keycloak, not built-in sign-in, manages users. */
  keycloakOn: boolean
  keycloakSaved: boolean
  paymentsOn: boolean
  paymentsSaved: boolean
  roleCount: number
  issues: ValidationIssue[] | null
  generationCount: number
}

/** Which section can fix an issue, judged by its path. */
export function sectionForIssue(issue: ValidationIssue): Section {
  if (issue.path === 'payments' || issue.path.startsWith('payments.')) return 'payments'
  if (issue.path.startsWith('auth.roles') || issue.path.startsWith('auth.permissions')) return 'access'
  if (issue.path === 'auth.keycloak' || issue.path.startsWith('auth.keycloak.')) return 'keycloak'
  if (issue.path === 'auth' || issue.path.startsWith('auth.')) return 'auth'
  return 'model'
}

interface Step {
  title: string
  detail: ReactNode
  done: boolean
  optional?: boolean
  section: Section
  action: string
}

export function OverviewPanel({
  projectId,
  entityCount,
  authEnabled,
  keycloakOn,
  keycloakSaved,
  paymentsOn,
  paymentsSaved,
  roleCount,
  issues,
  generationCount,
}: OverviewPanelProps) {
  const problemCount = issues?.length ?? 0

  const steps: Step[] = [
    {
      title: 'Design your data',
      detail:
        entityCount === 0
          ? 'Add the things your backend stores, such as posts or customers.'
          : `${entityCount} ${entityCount === 1 ? 'entity' : 'entities'} defined.`,
      done: entityCount > 0,
      section: 'model',
      action: entityCount > 0 ? 'Edit' : 'Start',
    },
    {
      title: 'Choose how people sign in',
      detail: authEnabled
        ? keycloakOn
          ? 'Sign-in is handled by Keycloak. Email, registration and token settings are here.'
          : 'Sign-in is on.'
        : 'Skip this if your API does not need user accounts.',
      done: authEnabled,
      optional: true,
      section: 'auth',
      action: authEnabled ? 'Edit' : 'Set up',
    },
  ]
  steps.push({
    title: 'Single sign-on with Keycloak',
    detail: keycloakOn
      ? 'Keycloak manages your users, with social logins, MFA and an admin console.'
      : 'Use Keycloak for sign-in, SSO across projects, Google or Microsoft logins and MFA.',
    done: keycloakOn,
    optional: true,
    section: 'keycloak',
    action: keycloakOn ? 'Edit' : keycloakSaved ? 'Turn on' : 'Set up',
  })
  steps.push({
    title: 'Take payments',
    detail: paymentsOn
      ? 'Card payments, refunds and disputes are switched on, with workers sized for your load.'
      : 'Hosted checkout with Stripe or Razorpay, refunds, an audit trail and deployment files sized for your traffic.',
    done: paymentsOn,
    optional: true,
    section: 'payments',
    action: paymentsOn ? 'Edit' : paymentsSaved ? 'Turn on' : 'Set up',
  })
  if (authEnabled) {
    steps.push({
      title: 'Decide who can do what',
      detail: roleCount === 0 ? 'Create roles, then give them access to your data.' : `${roleCount} roles defined.`,
      done: roleCount > 0,
      section: 'access',
      action: roleCount > 0 ? 'Edit' : 'Set up',
    })
  }
  steps.push({
    title: 'Generate your backend',
    detail:
      generationCount > 0
        ? `Downloaded ${generationCount} ${generationCount === 1 ? 'time' : 'times'}.`
        : 'Download a complete API with tests and Docker setup.',
    done: generationCount > 0,
    section: 'generate',
    action: generationCount > 0 ? 'Open' : 'Generate',
  })

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Overview</h1>
          <p>Work through these steps in any order. Come back here to see what is left.</p>
        </div>
      </div>

      {issues !== null && problemCount > 0 && entityCount > 0 && (
        <div className="card" style={{ marginBlockEnd: 'var(--space-6)' }}>
          <div role="alert" data-variant="danger" style={{ marginBlockEnd: 'var(--space-3)' }}>
            {problemCount} {problemCount === 1 ? 'thing needs' : 'things need'} fixing before you can generate.
          </div>
          <ul className="issue-list">
            {issues.map((issue, i) => (
              <li key={i}>
                <span>
                  {issue.message}
                  <small className="muted"> · {issue.path}</small>
                </span>
                <a className="button outline small" href={link(`/p/${projectId}/${sectionForIssue(issue)}`)}>
                  Fix
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <ol className="checklist">
        {steps.map((step) => (
          <li key={step.title} className={step.done ? 'done' : undefined}>
            <span className="check" aria-hidden="true">
              {step.done ? '✓' : ''}
            </span>
            <div className="checklist-text">
              <strong>
                {step.title}
                {step.optional && <span className="badge badge-outline">Optional</span>}
              </strong>
              <p className="muted">{step.detail}</p>
            </div>
            <a
              className={`button small${step.done ? ' outline' : ''}`}
              href={link(`/p/${projectId}/${step.section}`)}
            >
              {step.action}
            </a>
          </li>
        ))}
      </ol>
    </>
  )
}
