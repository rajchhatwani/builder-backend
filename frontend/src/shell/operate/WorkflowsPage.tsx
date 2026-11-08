import type { JsonSchema } from '../../forms'
import schema from '../../forms/schemas/workflows.json'
import { BlockFormPage } from '../connect/BlockFormPage'

/** Operate > Workflows: durable multi-step workflows with undo steps, editable through PUT /behavior/workflows.
 *  A step of kind "job" must name a declared job: the backend validator says so on save. */
export function WorkflowsPage({ projectId }: { projectId: string }) {
  return (
    <BlockFormPage projectId={projectId} path="workflows" key_="workflows" title="Workflows" schema={schema as JsonSchema}
      intro="Multi-step processes that survive restarts and undo finished steps when a later one fails." />
  )
}
