import { lazyScreen } from './lazy'

export const screens = {
  kit: lazyScreen(() => import('./KitScreen')),
  status: lazyScreen(() => import('../features/projects/StatusScreen')),
  projects: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.ProjectsScreen }))),
  signIn: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.SignInScreen }))),
  unavailable: lazyScreen(() => import('./EntryScreens').then(module => ({ default: module.Unavailable }))),
}
