import { lazyScreen } from './lazy'

export const screens = {
  code: lazyScreen(() => import('../features/editor/EditorScreen')),
  intake: lazyScreen(() => import('../features/guided/IntakeScreen')),
  plan: lazyScreen(() => import('../features/guided/PlanScreen')),
  build: lazyScreen(() => import('../features/guided/BuildScreen')),
  approvals: lazyScreen(() => import('../features/guided/ApprovalsScreen')),
  see: lazyScreen(() => import('../features/guided/SeeScreen')),
  kit: lazyScreen(() => import('./KitScreen')),
  status: lazyScreen(() => import('../features/projects/StatusScreen')),
  projects: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.ProjectsScreen }))),
  signIn: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.SignInScreen }))),
  unavailable: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.Unavailable }))),
}

export function sectionScreen(section: string) {
  if (section === 'code' || section === 'intake' || section === 'plan' || section === 'build' || section === 'approvals' || section === 'see') return screens[section]
  return screens.unavailable
}
