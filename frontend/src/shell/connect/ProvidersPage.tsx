import { Issues, Kv, Off, ReadOnlyNotice, SpecGate, Status, Scroll } from './BlockUi'
import { displaySetting, issuesFor } from './blockLogic'
import { useSpecBlocks } from './useSpecBlocks'

/** Connect > Integrations (providers): the adapters the spec allows and the resilience limits. Credentials are never part
 *  of the spec: each tenant stores its own through the generated, admin-only vault API. */
export function ProvidersPage({ projectId }: { projectId: string }) {
  const { load, reload } = useSpecBlocks(projectId)
  return (
    <SpecGate title="Provider integrations" load={load} retry={reload}
      intro="The email, SMS, payment, storage and other providers your project can talk to, with retries and a circuit breaker.">
      {({ spec, issues }) => {
        const p = spec.providers
        return (
          <>
            <ReadOnlyNotice what="The providers block" />
            <Issues issues={issuesFor(issues, 'providers')} />
            {!p || !p.enabled ? (
              <Off what="Provider integrations">Declare a <code>providers</code> block with <code>enabled: true</code>.</Off>
            ) : (
              <>
                <section aria-labelledby="pv-conf" className="card">
                  <h2 id="pv-conf">Resilience <Status on={p.enabled} /></h2>
                  <Kv items={[
                    ['Who may store credentials', <code key="r">{p.admin_role ?? 'admin'}</code>],
                    ['Timeout / attempts', `${p.timeout_seconds ?? 10} s / ${p.max_attempts ?? 3}`],
                    ['Circuit breaker', `opens after ${p.breaker_failures ?? 5} failures in a row, probes again after ${p.breaker_reset_seconds ?? 30} s`],
                  ]} />
                  <p className="muted">Credentials are never part of the spec. Each tenant stores its own through the generated project's
                    admin-only vault API (<code>/providers/credentials</code>); this page never shows or stores a secret.</p>
                </section>
                <section aria-labelledby="pv-list" className="card">
                  <h2 id="pv-list">Adapters</h2>
                  <p className="muted">Every kind always has the built-in <code>emulator</code>. These are the extra adapters a tenant may select.</p>
                  {(p.adapters ?? []).length === 0 ? <p className="muted" data-testid="pv-none">No adapters declared: only the emulator is available.</p> : (
                    <Scroll label="Declared provider adapters"><table className="bh-items" data-testid="pv-table">
                      <caption>Declared provider adapters</caption>
                      <thead><tr><th scope="col">Kind</th><th scope="col">Name</th><th scope="col">Settings (not secret)</th></tr></thead>
                      <tbody>
                        {(p.adapters ?? []).map((a) => (
                          <tr key={`${a.kind}/${a.name}`}>
                            <td>{a.kind}</td>
                            <td><code>{a.name}</code></td>
                            <td>{Object.keys(a.settings ?? {}).length === 0 ? 'none' : Object.entries(a.settings ?? {}).map(([k, v]) => `${k}: ${displaySetting(k, v)}`).join('; ')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table></Scroll>
                  )}
                </section>
              </>
            )}
          </>
        )
      }}
    </SpecGate>
  )
}
