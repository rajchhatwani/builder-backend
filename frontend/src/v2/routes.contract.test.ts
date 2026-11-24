import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { QueryClient } from '@tanstack/react-query'
import { createMemoryHistory } from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'
import { createAppRouter, routePaths } from './app/router'
import { projectKeys } from './features/projects/api/status'
import { detectLanguage } from './i18n'
import { desktopSections, guidedSections, isProjectSection, projectPath, statusSection } from './projectNavigation'
import { defaultLimits, validators } from './validators'

const openapi = JSON.parse(readFileSync(resolve(__dirname, '../../e2e/openapi.json'), 'utf8'))
const client = new QueryClient()
function routerAt(path: string) {
  return createAppRouter(client, createMemoryHistory({ initialEntries: [path] }))
}

describe('v2 route contract', () => {
  it('opens the projects entry and normalizes incomplete or unknown project routes to Home', async () => {
    const root = routerAt('/')
    await root.load()
    expect(root.state.location.pathname).toBe(routePaths.projects)
    for (const path of ['/projects/project-one', '/projects/project-one/unknown']) {
      const router = routerAt(path)
      await router.load()
      expect(router.state.location.pathname).toBe(projectPath('project-one'))
      expect(router.state.matches.at(-1)?.routeId).toBe(routePaths.status)
    }
  })

  it('matches the kit, sign-in, Guided steps and desktop-only routes', async () => {
    for (const path of [routePaths.kit, routePaths.signIn, ...[...guidedSections, ...desktopSections].map(section => projectPath('project-one', section))]) {
      const router = routerAt(path)
      await router.load()
      expect(router.state.location.pathname).toBe(path)
      expect(router.state.matches.at(-1)?.status).toBe('success')
    }
  })

  it('validates bookmarkable showcase state', () => {
    const router = routerAt('/v2-kit?state=unknown&page=-1&tab=third&sort=invalid')
    expect(router.matchRoutes(router.state.location).at(-1)?.search)
      .toMatchObject({ state: undefined, tab: undefined, page: 1, filter: '', sort: undefined })
  })

  it('uses only the three published operations on the status resource', () => {
    const statusApi = '/projects/{project_id}/status'
    const operations = Object.entries(openapi.paths as Record<string, Record<string, unknown>>)
      .filter(([path]) => path === statusApi || path.startsWith(statusApi + '/'))
      .flatMap(([path, item]) => Object.keys(item).filter(method => ['get', 'post', 'delete', 'put', 'patch'].includes(method)).map(method => `${method} ${path}`))
    expect(operations.sort()).toEqual([
      `delete ${statusApi}/dismiss/{step}`,
      `get ${statusApi}`,
      `post ${statusApi}/dismiss`,
    ])
  })

  it('shares one project status key across its consumers and maps backend section IDs to registered destinations', () => {
    expect(projectKeys.status('a')).toEqual(['projects', 'a', 'status'])
    expect(projectKeys.status('a')).not.toEqual(projectKeys.status('b'))
    for (const section of ['model', 'auth', 'authorization', 'payments', 'storage', 'observability', 'deployment', 'documents', 'state_machines', 'settings', 'history', 'hooks', 'seed', 'generate']) {
      expect(isProjectSection(statusSection(section))).toBe(true)
    }
    expect(statusSection('authorization')).toBe('access')
    expect(statusSection('state_machines')).toBe('machines')
  })
})

describe('language and validation contracts', () => {
  it('uses a saved choice before matching browser tags and falls back to English', () => {
    expect(detectLanguage('en', ['en-GB'])).toEqual({ language: 'en', source: 'saved' })
    expect(detectLanguage(null, ['fr', 'en-GB'])).toEqual({ language: 'en', source: 'browser' })
    expect(detectLanguage(null, ['fr'])).toEqual({ language: 'en', source: 'fallback' })
  })

  it('allows tighter field limits from OpenAPI than the generic defaults', () => {
    const schema = openapi.components.schemas.ProjectCreate.properties
    const nameLimit = Math.min(defaultLimits.shortText, 100)
    const descriptionLimit = Math.min(defaultLimits.longText, 2000)
    const serverDescriptionLimit = schema.description.anyOf.find((variant: { type: string }) => variant.type === 'string').maxLength
    expect(nameLimit).toBeLessThanOrEqual(schema.name.maxLength)
    expect(descriptionLimit).toBeLessThanOrEqual(serverDescriptionLimit)
    expect(validators.length(nameLimit)('a'.repeat(nameLimit))).toBeUndefined()
    expect(validators.length(nameLimit)('a'.repeat(nameLimit + 1))?.key).toBe('validation.maxLength')
    expect(validators.length(descriptionLimit)('a'.repeat(descriptionLimit + 1))?.key).toBe('validation.maxLength')
  })
})
