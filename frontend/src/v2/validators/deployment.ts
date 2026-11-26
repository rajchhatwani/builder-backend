// Request bounds from app/schemas/deployment.py and enabled-project rules from app/core/validation_deploy.py.
export const deploymentClouds = {
  aws: { region: 'eu-west-1', pattern: /^[a-z]{2}(?:-[a-z]+)+-\d$/, storage: [20, 16384] },
  azure: { region: 'westeurope', pattern: /^[a-z][a-z0-9]{3,24}$/, storage: [10, 32768] },
  gcp: { region: 'europe-west1', pattern: /^[a-z]+-[a-z]+\d+$/, storage: [10, 65536] },
}
export type DeployCloud = keyof typeof deploymentClouds
export const deployCloud = (value: string) => Object.hasOwn(deploymentClouds, value) ? deploymentClouds[value as DeployCloud] : undefined
export const deployProfiles = ['small', 'medium', 'large'] as const
export const deployNumbers = {
  min_instances: [-1, 100000],
  max_instances: [-1, 100000],
  cpu: [0, 1000000],
  memory: [0, 10000000],
  db_storage_gb: [0, 100000000],
} as const
export const deployFlags = ['db_high_availability', 'deletion_protection'] as const
export type DeployNumber = keyof typeof deployNumbers
export const deployNumberKeys: DeployNumber[] = ['min_instances', 'max_instances', 'cpu', 'memory', 'db_storage_gb']
export const deployLimits = { cloud: 10, region: 60, github_repo: 200, name: 40, profile: 10, environments: 50 }
export const suggestedDeployRegion = (cloud: string) => deployCloud(cloud)?.region ?? ''

type Environment = { name: string; profile: string } & Record<DeployNumber, string>
type Draft = { enabled: boolean; cloud: string; region: string; github_repo: string; environments: Environment[] }
type ErrorValue = { key: string; values?: Record<string, number | string> }
export type DeployErrors = Record<string, ErrorValue>

export function deploymentErrors(draft: Draft, sizes?: [number, number][], schemaOnly = false) {
  const errors: DeployErrors = {}
  const cloud = deployCloud(draft.cloud)
  const set = (path: string, key: string, values?: Record<string, number | string>) => { errors[path] ??= { key: 'ship.' + key, values } }
  const enabled = draft.enabled && !schemaOnly
  for (const key of ['cloud', 'region', 'github_repo'] as const) {
    if (draft[key].length > deployLimits[key]) set(key, 'length', { max: deployLimits[key] })
  }
  if (enabled) {
    if (!cloud) set('cloud', 'cloudInvalid')
    else if (!cloud.pattern.test(draft.region)) set('region', 'regionInvalid', { example: cloud.region })
    if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/.test(draft.github_repo)) set('github_repo', 'repoInvalid')
    if (draft.environments.length < 1 || draft.environments.length > 6) set('environments', 'environmentCount')
  }
  if (draft.environments.length > deployLimits.environments) set('environments', 'length', { max: deployLimits.environments })
  const names = new Set<string>()
  draft.environments.forEach((env, index) => {
    const path = 'env-' + index + '-'
    if (env.name.length > deployLimits.name) set(path + 'name', 'length', { max: deployLimits.name })
    if (env.profile.length > deployLimits.profile) set(path + 'profile', 'length', { max: deployLimits.profile })
    if (enabled) {
      if (!/^[a-z][a-z0-9]{1,11}$/.test(env.name)) set(path + 'name', 'nameInvalid')
      else if (names.has(env.name)) set(path + 'name', 'duplicateName')
      if (!deployProfiles.some(profile => profile === env.profile)) set(path + 'profile', 'profileInvalid')
    }
    names.add(env.name)
    for (const key of deployNumberKeys) {
      const value = env[key]
      const [min, max] = deployNumbers[key]
      if (value !== '' && (!/^-?\d{1,9}$/.test(value) || Number(value) < min || Number(value) > max)) {
        set(path + key, 'wholeNumber', { min, max })
      }
    }
    if (!enabled) return
    const numeric = (key: DeployNumber) => env[key] === '' ? null : Number(env[key])
    const cpu = numeric('cpu')
    const memory = numeric('memory')
    const min = numeric('min_instances')
    const max = numeric('max_instances')
    const storage = numeric('db_storage_gb')
    if ((cpu === null) !== (memory === null)) set(path + (cpu === null ? 'cpu' : 'memory'), 'sizePair')
    if (cpu !== null && memory !== null && sizes && !sizes.some(([c, m]) => c === cpu && m === memory)) set(path + 'cpu', 'offeredSize')
    const minimum = draft.cloud === 'aws' ? 1 : 0
    if (min !== null && (min < minimum || min > 100)) set(path + 'min_instances', 'wholeNumber', { min: minimum, max: 100 })
    if (max !== null && (max < 1 || max > 1000)) set(path + 'max_instances', 'wholeNumber', { min: 1, max: 1000 })
    if (min !== null && max !== null && max < min) set(path + 'max_instances', 'minMax')
    if (cloud && storage !== null && (storage < cloud.storage[0] || storage > cloud.storage[1])) {
      set(path + 'db_storage_gb', 'wholeNumber', { min: cloud.storage[0], max: cloud.storage[1] })
    }
  })
  return errors
}
