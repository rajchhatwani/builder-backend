import { useState } from 'react'
import { link } from '../../components/Sidebar'
import { countLine, issueSection, nextStepView, readAuthDismissed, routeFor, writeAuthDismissed } from './homeLogic'
import { useProjectStatus } from './useProjectStatus'

/** Home of the new shell: readiness board powered by GET /projects/{id}/status. */
export function HomePage({ projectId }: { projectId: string }) {
  const q = useProjectStatus(projectId)
  const [dismissed, setDismissed] = useState(() => readAuthDismissed(projectId))
  const status = q.data

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Home</h1>
          <p>Where your backend stands, what is blocking it, and the one thing to do next.</p>
        </div>
      </div>

      {q.isPending && <p className="empty-state">Loading project status…</p>}

      {q.isError && (
        <div className="card empty-hero" role="alert">
          <h2>We could not load the project status</h2>
          <p>{q.error instanceof Error ? q.error.message : 'Something went wrong.'}</p>
          <button onClick={() => void q.refetch()}>Try again</button>
        </div>
      )}

      {status && (
        <>
          {status.ready ? (
            <div role="status" className="home-banner home-ready" data-testid="readiness-banner" data-ready="true">
              <strong>Ready to generate.</strong> Nothing blocks your backend.
            </div>
          ) : (
            <div role="status" className="home-banner home-blocked" data-testid="readiness-banner" data-ready="false">
              <strong>Not ready yet.</strong>{' '}
              {status.issues.length > 0
                ? `${status.issues.length} ${status.issues.length === 1 ? 'thing needs' : 'things need'} fixing before you can generate.`
                : 'Add at least one entity before you can generate.'}
            </div>
          )}

          {(() => {
            const step = nextStepView(status.next_step, dismissed)
            return (
              <section className="card home-next" data-testid="next-step" data-step={step.id} aria-labelledby="next-step-title">
                <p className="muted small-text">Next step</p>
                <h2 id="next-step-title">{step.title}</h2>
                <p>{step.reason}</p>
                <div className="hstack">
                  <a className="button" href={link(`/p/${projectId}/${step.section}`)}>
                    {step.action}
                  </a>
                  {step.dismissible && (
                    <button
                      className="outline"
                      onClick={() => {
                        writeAuthDismissed(projectId, true)
                        setDismissed(true)
                      }}
                    >
                      Not now
                    </button>
                  )}
                </div>
              </section>
            )
          })()}

          {status.issues.length > 0 && (
            <section className="card" aria-labelledby="home-issues" data-testid="home-issues">
              <h2 id="home-issues">Problems to fix</h2>
              <ul className="issue-list">
                {status.issues.map((issue, i) => (
                  <li key={i}>
                    <span>
                      {issue.message}
                      <small className="muted"> · {issue.path}</small>
                    </span>
                    <a className="button outline small" href={link(`/p/${projectId}/${routeFor(issueSection(issue))}`)}>
                      Fix
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section aria-labelledby="home-sections">
            <h2 id="home-sections">Your project, section by section</h2>
            <ul className="home-sections" data-testid="home-sections">
              {status.sections.map((s) => (
                <li key={s.id} data-section={s.id}>
                  <div className="home-section-text">
                    <strong>{s.label}</strong>
                    <span className="muted small-text">
                      {s.issue_count > 0
                        ? `${s.issue_count} ${s.issue_count === 1 ? 'problem' : 'problems'}`
                        : s.configured
                          ? 'Set up'
                          : 'Not set up'}
                    </span>
                  </div>
                  <a className={`button small${s.configured || s.issue_count > 0 ? ' outline' : ''}`} href={link(`/p/${projectId}/${routeFor(s.id)}`)} aria-label={`${s.configured ? 'Open' : 'Set up'} ${s.label}`}>
                    {s.configured ? 'Open' : 'Set up'}
                  </a>
                </li>
              ))}
            </ul>
          </section>

          <p className="muted small-text" data-testid="home-counts">
            {['entities', 'relations', 'state_machines', 'settings', 'sequences', 'lists', 'history_configs', 'hooks', 'seed_profiles']
              .map((k) => countLine(status.counts, k))
              .filter(Boolean)
              .join(' · ')}
          </p>
        </>
      )}
    </>
  )
}
