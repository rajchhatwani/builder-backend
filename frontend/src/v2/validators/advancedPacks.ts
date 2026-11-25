const safeMoney = [1, Number.MAX_SAFE_INTEGER] as const
export const advancedPackLimits = {
  ranges: {
    'matchingsettings.weights.distance': [0, 1_000_000],
    'matchingsettings.weights.load': [0, 1_000_000],
    'matchingsettings.weights.rating': [0, 1_000_000],
    'matchingsettings.max_distance_m': [1, 20_037_509],
    'matchingsettings.max_load': [1, 1_000_000],
    'matchingsettings.offer_ttl_seconds': [1, 2_592_000],
    'predictionsettings.interval_bp': [0, 100_000],
    'aigatewaysettings.stages.*.max_output_tokens': [1, 100_000],
    'aigatewaysettings.budget.limit_micro_usd': safeMoney,
    'aigatewaysettings.budget.per_call_cap_micro_usd': safeMoney,
    'aidocssettings.review_below_bp': [0, 10_000],
    'aidocssettings.max_text_chars': [1, 2_000_000],
    'knowledgesettings.chunk_chars': [100, 5000],
    'knowledgesettings.max_sources': [1, 100_000],
    'knowledgesettings.max_text_chars': [1, 5_000_000],
    'agentssettings.agents.*.max_actions_per_run': [1, 20],
    'evalssettings.suites.*.pass_bp': [1, 10_000],
  } as Record<string, readonly [number, number]>,
  lists: {
    'aigatewaysettings.providers': 10, 'aigatewaysettings.stages': 50,
    'agentssettings.actions': 100, 'agentssettings.agents': 50,
    'evalssettings.suites': 50, 'evalssettings.suites.*.cases': 50,
  } as Record<string, number>,
  help: new Set(['read_roles', 'write_roles', 'assign_roles', 'upload_roles', 'review_roles', 'manage_roles', 'run_roles',
    'approve_roles', 'call_roles', 'model_id', 'unit', 'stage', 'region', 'zero_retention', 'byo_key_env', 'allow_self_review',
    'allow_self_approval', 'require_eval', 'expect_actions', 'forbid_actions', 'allowed_fields', 'risk', 'autonomy', 'max_autonomy']),
}

export const gatewayPrices = {
  'fake-embed': [20_000, 0],
  'fake-large': [3_000_000, 15_000_000],
  'fake-small': [150_000, 600_000],
} as const

export function gatewayOutputCost(tokens: unknown, ...models: unknown[]) {
  if (typeof tokens !== 'number' || !Number.isSafeInteger(tokens) || tokens < 1 || tokens > 100_000) return undefined
  const price = Math.max(0, ...models.map(model => gatewayPrices[model as keyof typeof gatewayPrices]?.[1] ?? 0))
  return Math.ceil((tokens * price) / 1_000_000)
}

type PackValidationPath = (string | number)[]
type PackValidationChoices = (path: PackValidationPath) => string[] | undefined

export function advancedPackIssues(screen: string, draft: Record<string, unknown>, choices: PackValidationChoices,
  label: (path: PackValidationPath) => string, t: (key: string, values?: Record<string, string | number>) => string) {
  const errors: Record<string, string[]> = {}
  const add = (path: PackValidationPath, key: string, values?: Record<string, string | number>) => {
    errors[path.join('.')] ??= []
    errors[path.join('.')].push(t('connectD.validation.' + key, { field: label(path), ...values }))
  }
  function validate(value: unknown, path: PackValidationPath) {
    const key = screen + '.' + path.map(part => typeof part === 'number' ? '*' : part).join('.')
    const field = path.at(-1)
    const bounds = advancedPackLimits.ranges[key]
    if (bounds && (typeof value !== 'number' || !Number.isSafeInteger(value) || value < bounds[0] || value > bounds[1])) {
      add(path, 'range', { min: bounds[0], max: bounds[1] })
    }
    const options = choices(path)
    if (options && (typeof value === 'string' && value !== '' && !options.includes(value) ||
      Array.isArray(value) && value.some(entry => typeof entry === 'string' && !options.includes(entry)))) {
      add(path, 'option')
    }
    if (Array.isArray(value)) {
      const max = advancedPackLimits.lists[key]
      if (max != null && value.length > max) add(path, 'entries', { max })
      const named = value.filter(item => item && typeof item === 'object' && 'name' in item).map(item => item.name)
      if (new Set(named).size < named.length) add(path, 'duplicate')
      if (new Set(value).size < value.length && ['fields', 'actions'].includes(String(field)) && screen === 'agentssettings') add(path, 'duplicate')
      if (!value.length && ['approve_roles', 'manage_roles', 'review_roles'].includes(String(field))) add(path, 'role')
      value.forEach((item, index) => validate(item, [...path, index]))
      return
    }
    if (value && typeof value === 'object') {
      const row = value as Record<string, unknown>
      if (field === 'weights' && [row.distance, row.load, row.rating].every(weight => weight === 0)) add(path, 'weights')
      if (field === 'budget' && Number(row.per_call_cap_micro_usd) > Number(row.limit_micro_usd)) add([...path, 'per_call_cap_micro_usd'], 'cap')
      if (screen === 'aigatewaysettings' && path[0] === 'stages') {
        if (row.fallback_model != null && row.fallback_model === row.model) add([...path, 'fallback_model'], 'fallback')
        const cost = gatewayOutputCost(row.max_output_tokens, row.model, row.fallback_model)
        const budget = draft.budget as Record<string, unknown> | undefined
        if (cost != null && cost > Number(budget?.per_call_cap_micro_usd)) add([...path, 'max_output_tokens'], 'outputCap')
      }
      if (screen === 'agentssettings' && path[0] === 'actions') {
        if (row.kind === 'entity_create' && !row.entity) add([...path, 'entity'], 'required')
        if (row.kind === 'entity_create' && Array.isArray(row.fields) && !row.fields.length) add([...path, 'fields'], 'required')
        if (row.kind === 'note' && (row.entity != null || Array.isArray(row.fields) && row.fields.length)) add([...path, 'fields'], 'note')
      }
      if (Array.isArray(row.expect_actions) && Array.isArray(row.forbid_actions)) {
        const forbidden = row.forbid_actions
        if (!row.expect_actions.length && !forbidden.length) add([...path, 'expect_actions'], 'expectation')
        if (row.expect_actions.some(action => forbidden.includes(action))) add([...path, 'forbid_actions'], 'contradictory')
      }
      Object.entries(row).forEach(([name, item]) => validate(item, [...path, name]))
      return
    }
    if (typeof value !== 'string') return
    const inCase = path.includes('cases')
    if (field === 'name') {
      if (inCase ? [...value].length < 1 || [...value].length > 120 :
        !(path[0] === 'stages' ? /^[a-z][a-z0-9_.-]{0,39}$/ : /^[a-z][a-z0-9_]{0,39}$/).test(value)) {
        add(path, inCase ? 'length' : path[0] === 'stages' ? 'stageName' : 'identifier', { max: 120 })
      }
    }
    if (field === 'goal' && (![...value].length || [...value].length > 4000)) add(path, 'length', { max: 4000 })
    if (field === 'description' && [...value].length > 500) add(path, 'description')
    if (field === 'region' && !/^[a-z0-9][a-z0-9-]{0,39}$/.test(value)) add(path, 'region')
    if (field === 'byo_key_env' && !/^[A-Z][A-Z0-9_]{0,63}$/.test(value)) add(path, 'environment')
    if (field === 'model_id' && (!/^[\p{L}\p{N}._-]+$/u.test(value) || !/[\p{L}\p{N}]/u.test(value) || [...value].length > 64)) add(path, 'modelId')
    if (field === 'unit' && (!/^[\p{L}\p{N}_]+$/u.test(value) || !/[\p{L}\p{N}]/u.test(value) || [...value].length > 16)) add(path, 'unit')
    if (['agent', 'provider', 'model', 'stage'].includes(String(field)) && !value) add(path, 'required')
  }
  validate(draft, [])
  return errors
}
