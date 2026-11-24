import { lazyScreen } from './lazy'

export const screens = {
  intake: lazyScreen(() => import('../features/guided/IntakeScreen')),
  plan: lazyScreen(() => import('../features/guided/PlanScreen')),
  kit: lazyScreen(() => import('./KitScreen')),
  status: lazyScreen(() => import('../features/projects/StatusScreen')),
  projects: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.ProjectsScreen }))),
  signIn: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.SignInScreen }))),
  unavailable: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.Unavailable }))),
}

export function sectionScreen(section: string) {
  if (section === 'intake' || section === 'plan') return screens[section]
  return screens.unavailable
}
