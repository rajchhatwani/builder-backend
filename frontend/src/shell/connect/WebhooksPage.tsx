import type { JsonSchema } from '../../forms'
import schema from '../../forms/schemas/webhooks.json'
import { PREVIEW_ORIGIN } from '../workbench/previewOrigin'
import { BlockFormPage } from './BlockFormPage'
import { useSpecBlocks } from './useSpecBlocks'
import { WebhookSubscriptions } from './WebhookSubscriptions'

/** Connect > Webhooks. The configuration (events, limits, receivers) is edited here through PUT /behavior/webhooks;
 *  subscriptions and signing secrets live in the generated project, so they are managed live against its API. */
export function WebhooksPage({ projectId, origin = PREVIEW_ORIGIN }: { projectId: string; origin?: string | null }) {
  const { load } = useSpecBlocks(projectId)
  const w = load.status === 'ready' ? load.spec.webhooks : null
  return (
    <div className="co-page">
      <BlockFormPage projectId={projectId} path="webhooks" key_="webhooks" title="Webhooks" schema={schema as JsonSchema}
        intro="Events your project sends to other systems (signed, retried, with a delivery log) and the incoming webhooks it accepts. Webhooks need events, jobs and providers to be switched on." />
      {w?.enabled && (origin ? (
        <WebhookSubscriptions origin={origin} events={w.events ?? []} inbound={(w.inbound ?? []).map((i) => i.name)} />
      ) : (
        <div className="card co-note" data-testid="wh-no-origin" role="note">
          <strong>Subscriptions and signing secrets are managed in the generated project.</strong> No preview API is configured for this
          builder (build setting <code>VITE_PREVIEW_API_ORIGIN</code>), so they cannot be listed or rotated from here yet.
        </div>
      ))}
    </div>
  )
}
