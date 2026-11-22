import type { JsonSchema } from '../../forms'
import gateway from '../../forms/schemas/ai-gateway.json'
import documents from '../../forms/schemas/ai-documents.json'
import knowledge from '../../forms/schemas/ai-knowledge.json'
import agents from '../../forms/schemas/ai-agents.json'
import evals from '../../forms/schemas/ai-evals.json'
import { PackFormPage } from '../packs/PackFormPage'

type P = { projectId: string }

export const AiGatewaySettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="ai" block="gateway" title="AI gateway settings" schema={gateway as JsonSchema}
    intro="Model providers, the per-stage router, the budget (integer micro-USD, estimates) and who may call, read and manage. Provider keys are never stored here." />
)
export const AiDocumentsSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="ai" block="documents" title="AI documents settings" schema={documents as JsonSchema}
    intro="Document kinds and their fields, the gateway stage used for extraction, who may upload, review and read, and the review threshold." />
)
export const KnowledgeSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="ai" block="knowledge" title="Knowledge settings" schema={knowledge as JsonSchema}
    intro="The answer stage, who may manage and read the knowledge library, and the chunk and size limits." />
)
export const AgentsSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="ai" block="agents" title="AI agents settings" schema={agents as JsonSchema}
    intro="The action registry (the only things an agent can do), the agents and their autonomy ceiling, and who may run, approve and read." />
)
export const EvalsSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="ai" block="evals" title="AI evals settings" schema={evals as JsonSchema}
    intro="Eval suites and their cases (every case runs its agent in dry mode), the pass mark and who may run them." />
)
