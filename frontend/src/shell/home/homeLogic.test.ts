import { describe, expect, it } from 'vitest'
import type { ProjectStatus } from '../../api/types'
import { countLine, issueSection, nextStepView, railProblems, routeFor, SECTION_ROUTE } from './homeLogic'
import { findSection } from '../pages'

const SECTION_IDS = ['model', 'auth', 'authorization', 'payments', 'storage', 'observability', 'deployment', 'documents', 'state_machines', 'settings', 'history', 'hooks', 'seed']

describe('home board mapping', () => {
  it('every one of the 13 backend sections links to a page that exists', () => {
    expect(Object.keys(SECTION_ROUTE).sort()).toEqual([...SECTION_IDS].sort())
    for (const id of SECTION_IDS) expect(findSection(routeFor(id)), id).toBeTruthy()
    expect(findSection(routeFor('generate'))).toBeTruthy()
  })

  it('issue paths land in the same section as the backend counts them', () => {
    const at = (path: string, code = 'x') => issueSection({ path, code })
    expect(at('entities[0].fields')).toBe('model')
    expect(at('auth.keycloak.realm')).toBe('auth')
    expect(at('auth.roles[1]')).toBe('authorization')
    expect(at('anything', 'authz.bad')).toBe('authorization')
    expect(at('anything', 'storage_required')).toBe('storage')
    expect(at('state_machines[0].transitions[1].when')).toBe('state_machines')
    expect(at('sequences[0]')).toBe('settings')
    expect(at('lists[2]')).toBe('settings')
    expect(at('hooks[0].budget')).toBe('hooks')
    expect(at('seed[0].plans')).toBe('seed')
    expect(at('unknown.thing')).toBe('model')
  })

  it('rail badges come from section issue counts, on the rail ids', () => {
    const status = {
      sections: [
        { id: 'state_machines', label: '', configured: true, issue_count: 2 },
        { id: 'authorization', label: '', configured: true, issue_count: 1 },
        { id: 'model', label: '', configured: true, issue_count: 0 },
      ],
    } as ProjectStatus
    expect(railProblems(status)).toEqual({ machines: 2, access: 1 })
    expect(railProblems(undefined)).toEqual({})
  })

  it('counts read in singular and plural', () => {
    expect(countLine({ entities: 1, hooks: 3 }, 'entities')).toBe('1 entity')
    expect(countLine({ entities: 1, hooks: 3 }, 'hooks')).toBe('3 hooks')
    expect(countLine({}, 'hooks')).toBeNull()
  })
})

describe('next step', () => {
  const step = (id: string, section: string) => ({ id, title: 'backend title', reason: 'because', section })

  it('maps the four ids to a title and a link target', () => {
    expect(nextStepView(step('fix_issues', 'state_machines'))).toMatchObject({ title: 'Fix what is blocking you', section: 'machines', reason: 'because', dismissible: false })
    expect(nextStepView(step('add_entity', 'model'))).toMatchObject({ title: 'Add your first entity', section: 'model' })
    expect(nextStepView(step('consider_auth', 'auth'))).toMatchObject({ title: 'Decide how people sign in', section: 'auth', dismissible: true })
    expect(nextStepView(step('generate', 'generate'))).toMatchObject({ title: 'Generate your backend', section: 'generate', dismissible: false })
  })

  it('an unknown id still gives one usable step', () => {
    expect(nextStepView(step('brand_new', 'hooks'))).toMatchObject({ title: 'backend title', section: 'hooks' })
  })
})
