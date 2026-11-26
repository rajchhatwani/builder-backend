import { suggestedDeployRegion } from '../../../validators/deployment'
import type { DeployNumber } from '../../../validators/deployment'
import type { DeployEnvironment, DeploymentSettings, DeploymentWrite } from '../api/ship'

export type EnvDraft = Omit<DeployEnvironment, DeployNumber> & Record<DeployNumber, string> & { row: number }
export type DeployDraft = Omit<DeploymentWrite, 'environments' | 'expected_version'> & { version: number; environments: EnvDraft[] }
type Edit = (
  | { type: 'settings'; patch: Partial<Pick<DeployDraft, 'enabled' | 'cloud' | 'region' | 'github_repo'>> }
  | { type: 'environment'; index: number; patch: Partial<Omit<EnvDraft, 'row'>> }
  | { type: 'add' }
  | { type: 'remove'; index: number }
  | { type: 'move'; index: number; delta: -1 | 1 }
) & { base: DeployDraft }

export function initialDeployment(settings: DeploymentSettings): DeployDraft {
  return {
    version: settings.version, enabled: settings.enabled, cloud: settings.cloud, region: settings.region, github_repo: settings.github_repo,
    environments: settings.environments.map((env, row) => ({
      ...env, row, min_instances: String(env.min_instances ?? ''), max_instances: String(env.max_instances ?? ''),
      cpu: String(env.cpu ?? ''), memory: String(env.memory ?? ''), db_storage_gb: String(env.db_storage_gb ?? ''),
    })),
  }
}

export function deploymentBody(draft: DeployDraft, guided: boolean, versioned = false): DeploymentWrite {
  const { enabled, cloud, github_repo, region, environments, version } = draft
  return {
    enabled, cloud, github_repo, region: guided && !region ? suggestedDeployRegion(cloud) : region,
    environments: environments.map(env => {
      const { row: _row, ...fields } = env
      const number = (key: DeployNumber) => env[key] === '' ? null : Number(env[key])
      return {
        ...fields, min_instances: number('min_instances'), max_instances: number('max_instances'),
        cpu: number('cpu'), memory: number('memory'), db_storage_gb: number('db_storage_gb'),
      }
    }),
    ...(versioned ? { expected_version: version } : {}),
  }
}

export function deploymentDraft(current: DeployDraft | null, action: Edit | { type: 'reset' }): DeployDraft | null {
  if (action.type === 'reset') return null
  const base = current ?? action.base
  const environments = [...base.environments]
  switch (action.type) {
    case 'settings': return { ...base, ...action.patch }
    case 'environment': return { ...base, environments: environments.map((env, i) => i === action.index ? { ...env, ...action.patch } : env) }
    case 'add': {
      const row = Math.max(-1, ...environments.map(env => env.row)) + 1
      let suffix = 1
      while (environments.some(env => env.name === 'env' + suffix)) suffix += 1
      return { ...base, environments: [...environments, { row, name: 'env' + suffix, profile: 'small', min_instances: '', max_instances: '', cpu: '', memory: '', db_storage_gb: '', db_high_availability: null, deletion_protection: null }] }
    }
    case 'remove': return { ...base, environments: environments.filter((_, i) => i !== action.index) }
    case 'move': {
      const other = action.index + action.delta
      if (!environments[action.index] || !environments[other]) return base
      const moved = environments[action.index]
      environments[action.index] = environments[other]
      environments[other] = moved
      return { ...base, environments }
    }
  }
}
