import { createRootRouteWithContext, createRoute, createRouter, redirect } from '@tanstack/react-router'
import type { QueryClient } from '@tanstack/react-query'
import { statusOptions } from '../features/projects/api/status'
import { useT } from '../i18n'
import { isProjectSection } from '../projectNavigation'
import { Button, EmptyState } from '../ui'
import { Shell } from './Shell'
import { LazyError, ScreenSkeleton } from './lazy'
import { screens } from './routeScreens'

type KitSearch = {
  state?: 'loading' | 'empty' | 'error'
  tab?: 'second'
  page: number
  filter: string
  sort?: 'descending' | 'ascending'
}

export const routePaths = {
  index: '/',
  projects: '/projects',
  signIn: '/sign-in',
  kit: '/v2-kit',
  project: '/projects/$projectId',
  status: '/projects/$projectId/overview',
  section: '/projects/$projectId/$section',
} as const

function NotFound() {
  const t = useT()
  return <EmptyState title={t('shell.notFound')} action={<Button asChild><a href={routePaths.projects}>{t('shell.projects')}</a></Button>} />
}

const root = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: Shell, notFoundComponent: NotFound, errorComponent: LazyError,
})
const index = createRoute({ getParentRoute: () => root, path: routePaths.index, beforeLoad: () => { throw redirect({ to: routePaths.projects }) } })
const projects = createRoute({ getParentRoute: () => root, path: routePaths.projects, component: screens.projects.Component })
const signIn = createRoute({ getParentRoute: () => root, path: routePaths.signIn, component: screens.signIn.Component })
const kit = createRoute({
  getParentRoute: () => root, path: routePaths.kit, component: screens.kit.Component,
  validateSearch: (search): KitSearch => ({
    state: search.state === 'loading' || search.state === 'empty' || search.state === 'error' ? search.state : undefined,
    tab: search.tab === 'second' ? 'second' : undefined,
    page: typeof search.page === 'number' && Number.isSafeInteger(search.page) && search.page > 0 ? search.page : 1,
    filter: typeof search.filter === 'string' ? search.filter : '',
    sort: search.sort === 'descending' || search.sort === 'ascending' ? search.sort : undefined,
  }),
})
const project = createRoute({
  getParentRoute: () => root, path: routePaths.project,
  beforeLoad: ({ params }) => { throw redirect({ to: routePaths.status, params }) },
})
const status = createRoute({
  getParentRoute: () => root, path: routePaths.status, component: screens.status.Component,
  loader: ({ context, params, preload }) => {
    if (preload) void context.queryClient.prefetchQuery(statusOptions(params.projectId))
  },
})
const section = createRoute({
  getParentRoute: () => root, path: routePaths.section, component: screens.unavailable.Component,
  beforeLoad: ({ params }) => {
    if (!isProjectSection(params.section)) throw redirect({ to: routePaths.status, params: { projectId: params.projectId } })
  },
})
export const routeTree = root.addChildren([index, projects, signIn, kit, project, status, section])

export function createAppRouter(queryClient: QueryClient, history?: ReturnType<typeof createRouter>['history']) {
  return createRouter({ routeTree, context: { queryClient }, history, defaultPreload: 'intent', defaultPendingComponent: ScreenSkeleton })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
