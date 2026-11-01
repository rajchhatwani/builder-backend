import { PREVIEW_ORIGIN } from '../workbench/previewOrigin'
import { Issues, Kv, Off, ReadOnlyNotice, SpecGate, Status, Scroll } from './BlockUi'
import { issuesFor, urlPolicyText } from './blockLogic'
import { useSpecBlocks } from './useSpecBlocks'
import { WebhookSubscriptions } from './WebhookSubscriptions'

/** Connect > Webhooks. The configuration (events, limits, receivers) is read from the spec; subscriptions and signing
 *  secrets live in the generated project, so they are managed live against its API (see WebhookSubscriptions). */
export function WebhooksPage({ projectId, origin = PREVIEW_ORIGIN }: { projectId: string; origin?: string | null }) {
  const { load, reload } = useSpecBlocks(projectId)
  return (
    <SpecGate title="Webhooks" load={load} retry={reload}
      intro="Events your project sends to other systems (signed, retried, with a delivery log) and the incoming webhooks it accepts.">
      {({ spec, issues }) => {
        const w = spec.webhooks
        return (
          <>
            <ReadOnlyNotice what="The webhooks configuration" />
            <Issues issues={issuesFor(issues, 'webhooks')} />
            {!w || !w.enabled ? (
              <Off what="Webhooks">Declare a <code>webhooks</code> block with <code>enabled: true</code> (it needs events, jobs and providers).</Off>
            ) : (
              <>
                <section aria-labelledby="wh-conf" className="card">
                  <h2 id="wh-conf">Configuration <Status on={w.enabled} /></h2>
                  <Kv items={[
                    ['Who may manage it', <code key="r">{w.admin_role ?? 'admin'}</code>],
                    ['Where deliveries may go', urlPolicyText(w.allow_http, w.allowed_ports)],
                    ['Timeout / largest payload', `${w.timeout_seconds ?? 10} s / ${w.max_payload_bytes ?? 262144} bytes`],
                    ['Turned off after', `${w.max_consecutive_failures ?? 5} failures in a row`],
                    ['Old secret keeps working for', `${w.secret_overlap_hours ?? 24} hours after a rotation`],
                  ]} />
                  <h3>Events that can be subscribed to</h3>
                  {(w.events ?? []).length === 0 ? <p className="muted" data-testid="wh-no-events">None listed: nothing can be subscribed to (default deny).</p> : (
                    <ul className="co-chips" data-testid="wh-events">{(w.events ?? []).map((e) => <li key={e}><code>{e}</code></li>)}</ul>
                  )}
                </section>
                <section aria-labelledby="wh-in" className="card">
                  <h2 id="wh-in">Incoming receivers</h2>
                  {(w.inbound ?? []).length === 0 ? <p className="muted">No incoming webhooks declared.</p> : (
                    <Scroll label="Incoming webhook receivers"><table className="bh-items" data-testid="wh-inbound">
                      <caption>Incoming webhook receivers</caption>
                      <thead><tr><th scope="col">Endpoint</th><th scope="col">Signature window</th><th scope="col">Largest body</th><th scope="col">Duplicates remembered</th></tr></thead>
                      <tbody>
                        {(w.inbound ?? []).map((i) => (
                          <tr key={i.name}><td><code>POST /webhooks/in/{i.name}</code></td><td>{i.tolerance_seconds ?? 300} s</td><td>{i.max_body_bytes ?? 262144} bytes</td><td>{i.dedupe_days ?? 7} days</td></tr>
                        ))}
                      </tbody>
                    </table></Scroll>
                  )}
                </section>
                {origin ? (
                  <WebhookSubscriptions origin={origin} events={w.events ?? []} inbound={(w.inbound ?? []).map((i) => i.name)} />
                ) : (
                  <div className="card co-note" data-testid="wh-no-origin" role="note">
                    <strong>Subscriptions and signing secrets are managed in the generated project.</strong> No preview API is configured for this
                    builder (build setting <code>VITE_PREVIEW_API_ORIGIN</code>), so they cannot be listed or rotated from here yet.
                  </div>
                )}
              </>
            )}
          </>
        )
      }}
    </SpecGate>
  )
}
