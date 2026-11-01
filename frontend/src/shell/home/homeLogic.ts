import type { NextStep, ProjectStatus, ValidationIssue } from '../../api/types'
import type { AnySection } from '../pages'

/** Where each of the 13 status sections is edited. Pages that exist in the v2 shell link to them;
 *  the rest link to the old panels' routes (same deep links as before). */
export const SECTION_ROUTE: Record<string, AnySection> = {
  model: 'model',
  auth: 'auth',
  authorization: 'access',
  payments: 'payments',
  storage: 'storage',
  observability: 'observability',
  deployment: 'deployment',
  documents: 'documents',
  state_machines: 'machines',
  settings: 'settings',
  history: 'history',
  hooks: 'hooks',
  seed: 'seed',
}

/** Route (section id) for a backend section id; 'generate' and unknown ids are handled by the caller. */
export function routeFor(sectionId: string): AnySection {
  if (sectionId === 'generate') return 'generate'
  return SECTION_ROUTE[sectionId] ?? 'model'
}

/** Same judgement as the backend's issue_area (app/services/status_service.py), so the Fix link of an issue
 *  matches the section card that counts it. */
export function issueSection(issue: Pick<ValidationIssue, 'path' | 'code'>): string {
  if (issue.code === 'storage_required') return 'storage'
  if (issue.code.startsWith('authz.')) return 'authorization'
  const head = issue.path.split('.', 1)[0].split('[', 1)[0]
  if (head === 'auth' && (issue.path.startsWith('auth.roles') || issue.path.startsWith('auth.permissions'))) return 'authorization'
  if (head === 'sequences' || head === 'lists') return 'settings'
  return head in SECTION_ROUTE ? head : 'model'
}

/** Issue counts per rail item (the badges), from the same status call as the board. Keycloak issues are
 *  counted under Authentication by the backend, so the Keycloak rail item gets no badge. */
export function railProblems(status: ProjectStatus | undefined): Partial<Record<AnySection, number>> {
  const out: Partial<Record<AnySection, number>> = {}
  for (const s of status?.sections ?? []) {
    if (s.issue_count > 0) out[routeFor(s.id)] = s.issue_count
  }
  return out
}

export interface NextStepView {
  id: string
  title: string
  reason: string
  action: string
  section: AnySection
  /** Only the sign-in suggestion can be set aside ("Not now"). */
  dismissible: boolean
}

const TITLES: Record<string, { title: string; action: string }> = {
  fix_issues: { title: 'Fix what is blocking you', action: 'Fix it' },
  add_entity: { title: 'Add your first entity', action: 'Add an entity' },
  consider_auth: { title: 'Decide how people sign in', action: 'Set up sign-in' },
  generate: { title: 'Generate your backend', action: 'Generate' },
}

/** Exactly one step. consider_auth has no backend skip state: when the user said "Not now", the next
 *  step is Generate (the backend only suggests sign-in once nothing blocks generating). */
export function nextStepView(step: NextStep, authDismissed: boolean): NextStepView {
  if (step.id === 'consider_auth' && authDismissed) {
    return { id: 'generate', ...TITLES.generate, reason: 'You can add sign-in later. Download a complete API with tests and Docker setup.', section: 'generate', dismissible: false }
  }
  const t = TITLES[step.id] ?? { title: step.title, action: 'Open' }
  return { id: step.id, title: t.title, action: t.action, reason: step.reason, section: routeFor(step.section), dismissible: step.id === 'consider_auth' }
}

export const COUNT_LABELS: [key: string, one: string, many: string][] = [
  ['entities', 'entity', 'entities'],
  ['relations', 'relation', 'relations'],
  ['state_machines', 'state machine', 'state machines'],
  ['settings', 'setting', 'settings'],
  ['sequences', 'sequence', 'sequences'],
  ['lists', 'list', 'lists'],
  ['history_configs', 'history rule', 'history rules'],
  ['hooks', 'hook', 'hooks'],
  ['seed_profiles', 'seed profile', 'seed profiles'],
]

export function countLine(counts: Record<string, number>, key: string): string | null {
  const row = COUNT_LABELS.find((c) => c[0] === key)
  if (!row || counts[key] === undefined) return null
  const n = counts[key]
  return `${n} ${n === 1 ? row[1] : row[2]}`
}

const skipKey = (projectId: string) => `home.skipAuth.${projectId}`

export function readAuthDismissed(projectId: string, storage?: Pick<Storage, 'getItem'>): boolean {
  try {
    return (storage ?? window.localStorage).getItem(skipKey(projectId)) === '1'
  } catch {
    return false
  }
}

export function writeAuthDismissed(projectId: string, value: boolean, storage?: Pick<Storage, 'setItem' | 'removeItem'>): void {
  try {
    const s = storage ?? window.localStorage
    if (value) s.setItem(skipKey(projectId), '1')
    else s.removeItem(skipKey(projectId))
  } catch {
    /* private window or blocked storage: the dismissal just lasts until reload */
  }
}
