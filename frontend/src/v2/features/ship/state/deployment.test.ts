import { describe, expect, it } from 'vitest'
import { deployment } from '../../../../../e2e/v2/fixtures/ship'
import { deploymentErrors } from '../../../validators/deployment'
import { deploymentBody, deploymentDraft, initialDeployment } from './deployment'

describe('deployment draft', () => {
  it('retains the loaded version, NULL overrides and user ordering across edits', () => {
    const base = initialDeployment(deployment)
    const overridden = deploymentDraft(null, { type: 'environment', base, index: 1, patch: { deletion_protection: false } })
    const moved = deploymentDraft(overridden, { type: 'move', base, index: 1, delta: -1 })!
    const body = deploymentBody(moved, true, true)
    expect(body.expected_version).toBe(3)
    expect(body.environments.map(row => [row.name, row.deletion_protection])).toEqual([['prod', false], ['dev', null]])
    expect(body.environments[0]).not.toHaveProperty('row')
    const cleared = deploymentDraft(moved, { type: 'environment', base, index: 0, patch: { deletion_protection: null } })!
    expect(deploymentBody(cleared, false).environments[0].deletion_protection).toBeNull()
  })

  it('checks cloud-specific syntax and numeric overrides without losing invalid text', () => {
    const base = initialDeployment(deployment)
    const changed = deploymentDraft(null, { type: 'environment', base, index: 0,
      patch: { cpu: '512', min_instances: '0', db_storage_gb: '19' } })!
    expect(deploymentErrors({ ...changed, region: 'invalid' })).toMatchObject({
      region: { key: 'ship.regionInvalid' },
      'env-0-memory': { key: 'ship.sizePair' },
      'env-0-min_instances': { key: 'ship.wholeNumber', values: { min: 1, max: 100 } },
      'env-0-db_storage_gb': { key: 'ship.wholeNumber', values: { min: 20, max: 16384 } },
    })
    expect(deploymentErrors(changed, undefined, true)).toEqual({})
  })
})
