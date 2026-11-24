import { createRootRouteWithContext, createRoute, createRouter, redirect } from '@tanstack/react-router'
import type { QueryClient } from '@tanstack/react-query'
import { PreviewCredentials } from '../features/guided/components/PreviewCredentials'
import { statusOptions } from '../features/projects/api/status'
import { useT } from '../i18n'
import { isProjectSection, type SectionSearch } from '../projectNavigation'
import { Button, EmptyState } from '../ui'
import { Shell } from './Shell'
import { LazyError, ScreenSkeleton } from './lazy'
import { screens, sectionScreen } from './routeScreens'

export { openInEditor } from '../features/editor/routes'

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
  getParentRoute: () => root, path: routePaths.section, component: ProjectSection,
  validateSearch: (search): SectionSearch => ({
    tab: typeof search.tab === 'string' ? search.tab : undefined,
    kind: typeof search.kind === 'string' ? search.kind : undefined,
    risk: typeof search.risk === 'string' ? search.risk : undefined,
    decision: typeof search.decision === 'string' ? search.decision : undefined,
    owner: typeof search.owner === 'string' ? search.owner : undefined,
    preview: typeof search.preview === 'string' ? search.preview : undefined,
    entity: typeof search.entity === 'string' ? search.entity : undefined,
    file: typeof search.file === 'string' ? search.file : undefined,
    openFiles: Array.isArray(search.openFiles) ? [...new Set(search.openFiles.filter((file): file is string => typeof file === 'string'))] : undefined,
    source: search.source === 'manifest' || search.source === 'kit' ? search.source : undefined,
    q: typeof search.q === 'string' ? search.q : undefined,
    line: typeof search.line === 'number' && Number.isSafeInteger(search.line) && search.line > 0 ? search.line : undefined,
    tool: typeof search.tool === 'string' ? search.tool : undefined,
    view: typeof search.view === 'string' ? search.view : undefined,
    role: typeof search.role === 'string' ? search.role : undefined,
    history: typeof search.history === 'number' && Number.isSafeInteger(search.history) && search.history > 1 ? search.history : undefined,
    approval: typeof search.approval === 'string' ? search.approval : undefined,
    page: typeof search.page === 'number' && Number.isSafeInteger(search.page) && search.page > 1 ? search.page : undefined,
    run: typeof search.run === 'string' ? search.run : undefined,
    phase: typeof search.phase === 'number' && Number.isInteger(search.phase) && search.phase >= 1 && search.phase <= 10 ? search.phase : undefined,
    workspace: typeof search.workspace === 'string' ? search.workspace : undefined,
  }),
  loaderDeps: ({ search }) => ({ run: search.run, page: search.page, approval: search.approval, history: search.history, source: search.source, workspace: search.workspace }),
  loader: ({ context, params, deps, preload }) => {
    if (!preload) return
    if (params.section === 'code' && (typeof document === 'undefined' || document.body.clientWidth >= 700)) {
      void import('../features/editor/api/editor').then(({ filesOptions, manifestOptions, kitOptions }) => {
        const id = params.projectId
        if (deps.workspace) void context.queryClient.prefetchQuery(filesOptions(id, deps.workspace))
        else if (deps.source === 'manifest') void context.queryClient.prefetchQuery(manifestOptions(id))
        else void context.queryClient.prefetchQuery(kitOptions(id))
      }, () => undefined)
    }
    if (params.section === 'intake' || params.section === 'plan') {
      void import('../features/guided/api/guided').then(({ mapOptions, approvalOptions }) => {
        if (params.section === 'intake') void context.queryClient.prefetchQuery(mapOptions(params.projectId))
        else void context.queryClient.prefetchQuery(approvalOptions(params.projectId, deps.run))
      }, () => undefined)
    }
    if (params.section === 'build' || params.section === 'approvals' || params.section === 'see') {
      void import('../features/guided/api/delivery').then(({ runsOptions, runOptions, inboxOptions, reviewOptions, previewsOptions }) => {
        if (params.section === 'build') {
          void context.queryClient.prefetchQuery(runsOptions(params.projectId, deps.history))
          if (deps.run) void context.queryClient.prefetchQuery(runOptions(params.projectId, deps.run, deps.page))
        } else if (params.section === 'see') {
          void context.queryClient.prefetchQuery(previewsOptions(params.projectId))
        } else if (deps.approval) {
          void context.queryClient.prefetchQuery(reviewOptions(params.projectId, deps.approval))
        } else {
          void context.queryClient.prefetchQuery(inboxOptions(params.projectId, ['pending']))
        }
      }, () => undefined)
    }
  },
  beforeLoad: ({ params }) => {
    if (!isProjectSection(params.section)) throw redirect({ to: routePaths.status, params: { projectId: params.projectId } })
  },
})
function ProjectSection() {
  const { projectId, section: name } = section.useParams()
  const Screen = sectionScreen(name).Component
  return <PreviewCredentials key={projectId}><Screen /></PreviewCredentials>
}

export const routeTree = root.addChildren([index, projects, signIn, kit, project, status, section])

export function createAppRouter(queryClient: QueryClient, history?: ReturnType<typeof createRouter>['history']) {
  return createRouter({ routeTree, context: { queryClient }, history, defaultPreload: 'intent', defaultPendingComponent: ScreenSkeleton })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
