import matching from '../../../../forms/schemas/matching.json'
import prediction from '../../../../forms/schemas/prediction.json'
import gateway from '../../../../forms/schemas/ai-gateway.json'
import documents from '../../../../forms/schemas/ai-documents.json'
import knowledge from '../../../../forms/schemas/ai-knowledge.json'
import agents from '../../../../forms/schemas/ai-agents.json'
import evals from '../../../../forms/schemas/ai-evals.json'
import { orderedKeys, resolve } from '../../../../forms/schemaLogic'
import type { JsonSchema } from '../../../../forms/types'
import { advancedPackLimits } from '../../../validators/advancedPacks'
import type { PackAddress, PackBlock } from '../api/packs'

export const advancedPackDefinitions = {
  matchingsettings: {
    address: ['operations', 'matching'], schema: matching as JsonSchema,
    groups: { access: ['read_roles', 'assign_roles'], weights: ['weights'], offers: ['max_distance_m', 'max_load', 'offer_ttl_seconds'] },
    requiredPacks: [], related: ['locationsettings'], tables: ['match_assignments'], route: '/matching',
  },
  predictionsettings: {
    address: ['operations', 'prediction'], schema: prediction as JsonSchema,
    groups: { access: ['read_roles', 'write_roles'], records: ['model_id', 'unit', 'interval_bp'] },
    requiredPacks: [], related: [], tables: ['prediction_records'], route: '/prediction',
  },
  aigatewaysettings: {
    address: ['ai', 'gateway'], schema: gateway as JsonSchema,
    groups: { data: ['region', 'zero_retention'], providers: ['providers'], stages: ['stages'], budget: ['budget'], access: ['roles'] },
    requiredPacks: [], related: ['aidocssettings', 'knowledgesettings', 'agentssettings', 'evalssettings'],
    tables: ['ai_calls', 'ai_budget_periods'], route: '/ai',
  },
  aidocssettings: {
    address: ['ai', 'documents'], schema: documents as JsonSchema,
    groups: { extraction: ['stage', 'review_below_bp', 'max_text_chars', 'allow_self_review'], kinds: ['kinds'],
      access: ['upload_roles', 'review_roles', 'read_roles'] },
    requiredPacks: ['aigatewaysettings'], related: [], tables: ['ai_documents', 'ai_document_fields'], route: '/ai/documents',
  },
  knowledgesettings: {
    address: ['ai', 'knowledge'], schema: knowledge as JsonSchema,
    groups: { answers: ['stage'], access: ['manage_roles', 'read_roles'], sources: ['chunk_chars', 'max_sources', 'max_text_chars'] },
    requiredPacks: ['aigatewaysettings'], related: [], tables: ['ai_knowledge_sources', 'ai_knowledge_chunks'], route: '/ai/knowledge',
  },
  agentssettings: {
    address: ['ai', 'agents'], schema: agents as JsonSchema,
    groups: { actions: ['actions'], agents: ['agents'], access: ['roles'], approval: ['allow_self_approval'] },
    requiredPacks: ['aigatewaysettings'], related: ['evalssettings'],
    tables: ['ai_agent_runs', 'ai_agent_proposals'], route: '/ai/agents',
  },
  evalssettings: {
    address: ['ai', 'evals'], schema: evals as JsonSchema,
    groups: { suites: ['suites'], access: ['run_roles'] },
    requiredPacks: ['agentssettings'], related: [], tables: ['ai_eval_runs'], route: '/ai/evals',
  },
} as const satisfies Record<string, {
  address: PackAddress; schema: JsonSchema; groups: Record<string, readonly string[]>
  requiredPacks: readonly string[]; related: readonly string[]; tables: readonly string[]; route: string
}>

export type AdvancedPackScreen = keyof typeof advancedPackDefinitions
export type Translate = (key: string, values?: Record<string, string | number>) => string

export const record = (value: unknown): PackBlock => value && typeof value === 'object' && !Array.isArray(value) ? value as PackBlock : {}
export const rows = (value: unknown) => Array.isArray(value) ? value.map(record) : []
export const names = (values: unknown) => rows(values).flatMap(row => typeof row.name === 'string' && row.name ? [row.name] : [])
export const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []

export function displaySchema(screen: AdvancedPackScreen, t: Translate): JsonSchema {
  const root = advancedPackDefinitions[screen].schema as JsonSchema
  function decorate(source: JsonSchema, path: string): JsonSchema {
    const { nullable, description: _description, title: _title, ...node } = resolve(root, source)
    const field = path.split('.').at(-1) ?? ''
    const hint = node['x-ui']
    const key = screen + '.' + path
    const range = advancedPackLimits.ranges[key]
    const listLimit = advancedPackLimits.lists[key]
    const fieldKey = path === 'actions.*.fields' ? 'allowed_fields' : field
    const helpKey = field.endsWith('_roles') ? field : fieldKey
    const label = t('connectD.field.' + fieldKey)
    const help = range ? t('connectD.range', { min: range[0], max: range[1] }) :
      advancedPackLimits.help.has(helpKey) ? t('connectD.help.' + helpKey) : undefined
    const shape: JsonSchema = {
      ...node,
      ...(listLimit != null ? { maxItems: listLimit } : {}),
      'x-ui': {
        ...hint,
        ...(field && field !== '*' ? { label } : {}),
        ...(hint?.itemLabel ? { itemLabel: t('connectD.item.' + field) } : {}),
        help,
        ...(field === 'goal' || field === 'description' ? { widget: 'textarea' } : {}),
      },
      ...(node.properties ? { properties: Object.fromEntries(orderedKeys(node).map(name =>
        [name, decorate(node.properties![name], path ? path + '.' + name : name)])) } : {}),
      ...(node.items ? { items: decorate(node.items, path + '.*') } : {}),
    }
    return nullable ? { anyOf: [shape, { type: 'null' }] } : shape
  }
  return decorate(root, '')
}

export function packGroups(screen: AdvancedPackScreen, schema: JsonSchema) {
  return Object.entries(advancedPackDefinitions[screen].groups).map(([group, fields]) => ({
    group, fields, schema: { type: 'object', properties: Object.fromEntries((fields as readonly string[]).map(field => [field, schema.properties![field]])) },
  }))
}
