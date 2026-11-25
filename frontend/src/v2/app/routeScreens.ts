import { lazyScreen } from './lazy'

export const screens = {
  diagrams: lazyScreen(() => import('../features/diagrams/DiagramsScreen')),
  code: lazyScreen(() => import('../features/editor/EditorScreen')),
  intake: lazyScreen(() => import('../features/guided/IntakeScreen')),
  plan: lazyScreen(() => import('../features/guided/PlanScreen')),
  build: lazyScreen(() => import('../features/guided/BuildScreen')),
  approvals: lazyScreen(() => import('../features/guided/ApprovalsScreen')),
  see: lazyScreen(() => import('../features/guided/SeeScreen')),
  hooks: lazyScreen(() => import('../features/build-behavior/HooksScreen')),
  hookeffects: lazyScreen(() => import('../features/build-behavior/EffectsScreen')),
  events: lazyScreen(() => import('../features/build-behavior/EventsScreen')),
  settings: lazyScreen(() => import('../features/build-behavior/SettingsScreen')),
  seed: lazyScreen(() => import('../features/build-behavior/SeedScreen')),
  customfields: lazyScreen(() => import('../features/build-behavior/CustomFieldsScreen')),
  kit: lazyScreen(() => import('./KitScreen')),
  status: lazyScreen(() => import('../features/projects/StatusScreen')),
  projects: lazyScreen(() => import('../features/entry/ProjectsScreen')),
  newProject: lazyScreen(() => import('../features/entry/NewProjectScreen')),
  account: lazyScreen(() => import('../features/entry/AccountScreen')),
  signIn: lazyScreen(() => import('../features/entry/SignInScreen')),
  signup: lazyScreen(() => import('../features/entry/SignupScreen')),
  verifyEmail: lazyScreen(() => import('../features/entry/VerifyEmailScreen')),
  ssoComplete: lazyScreen(() => import('../features/entry/SsoCompleteScreen')),
  invitations: lazyScreen(() => import('../features/entry/InvitationsScreen')),
  organization: lazyScreen(() => import('../features/entry/OrganizationLandingScreen')),
  choosePassword: lazyScreen(() => import('../features/entry/ChoosePasswordScreen')),
  unavailable: lazyScreen<Record<string, never>>(() => import('./EntryScreens').then(module => ({ default: module.Unavailable }))),
}

export function sectionScreen(section: string) {
  if (section === 'code' || section === 'intake' || section === 'plan' || section === 'build' || section === 'approvals' || section === 'see') return screens[section]
  return screens.unavailable
}
