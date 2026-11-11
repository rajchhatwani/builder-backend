import type { JsonSchema } from '../../forms'
import apiEdge from '../../forms/schemas/api-edge.json'
import events from '../../forms/schemas/events.json'
import hookEffects from '../../forms/schemas/hook-effects.json'
import notifications from '../../forms/schemas/notifications.json'
import { BlockFormPage } from './BlockFormPage'

/** FX-10 / F-004: the spec blocks that had an endpoint (PUT /behavior/{events,api-edge,hook-effects,notifications}) but no page.
 *  Each is the generic spec-backed form (BlockFormPage): load, edit, whole-block PUT with expected_version, 409 and 422 shown. */
export function EventsPage({ projectId }: { projectId: string }) {
  return (
    <BlockFormPage projectId={projectId} path="events" key_="events" title="Events" schema={events as JsonSchema}
      intro="The outbox that turns changes into events other parts (webhooks, notifications, hooks) react to: which adapter delivers them and how long they are kept." />
  )
}

export function ApiEdgePage({ projectId }: { projectId: string }) {
  return (
    <BlockFormPage projectId={projectId} path="api-edge" key_="api_edge" title="API edge" schema={apiEdge as JsonSchema}
      intro="Idempotency keys, rate limits, quotas and dated API versions for the generated API. Each part is on when its section is filled in." />
  )
}

export function HookEffectsPage({ projectId }: { projectId: string }) {
  return (
    <BlockFormPage projectId={projectId} path="hook-effects" key_="hook_effects" title="Hook effects" schema={hookEffects as JsonSchema}
      intro="Lets custom hooks make outbound calls. Off unless switched on; only trusted authors may write such hooks, and calls may only go to the hosts listed here." />
  )
}

export function NotificationTypesPage({ projectId }: { projectId: string }) {
  return (
    <BlockFormPage projectId={projectId} path="notifications" key_="notifications" title="Notification types" schema={notifications as JsonSchema}
      intro="Which notifications the project can send (email, SMS, push), their default templates, and the event that triggers each. Needs providers and sign-in. The delivery log is on the Notifications page." />
  )
}
