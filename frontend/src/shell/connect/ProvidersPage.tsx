import type { JsonSchema } from '../../forms'
import schema from '../../forms/schemas/providers.json'
import { BlockFormPage } from './BlockFormPage'

/** Connect > Integrations (providers): the adapters the spec allows and the resilience limits, editable through
 *  PUT /behavior/providers. Credentials are never part of the spec and never shown or entered here: each tenant stores
 *  its own through the generated project's admin-only vault API. The builder rejects a secret-looking setting (422). */
export function ProvidersPage({ projectId }: { projectId: string }) {
  return (
    <BlockFormPage projectId={projectId} path="providers" key_="providers" title="Provider integrations" schema={schema as JsonSchema}
      intro="The email, SMS, payment, storage and other providers your project can talk to, with retries and a circuit breaker."
      status={() => (
        <>Credentials are never part of the spec. Each tenant stores its own through the generated project's admin-only vault API
          (<code>/providers/credentials</code>); this page has no secret fields and never shows a stored secret. Adapter settings must not be secret.</>
      )} />
  )
}
