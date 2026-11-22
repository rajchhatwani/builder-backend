import { ApiError } from '../../api/client'
import type { ScorecardCheck, UpgradeBlockChange, UpgradeFile, UpgradeSbomDiff, UpgradeSbomEntry } from '../../api/types'

export const GROUPS: { id: string; label: string }[] = [
  { id: 'security', label: 'Security' },
  { id: 'dependency_freshness', label: 'Dependency freshness' },
  { id: 'hook_coverage', label: 'Hook coverage' },
  { id: 'block_version_lag', label: 'Block version lag' },
  { id: 'drift', label: 'Drift' },
]

export function groupChecks(checks: ScorecardCheck[]): { id: string; label: string; checks: ScorecardCheck[] }[] {
  const known = new Set(GROUPS.map((g) => g.id))
  const out = GROUPS.map((g) => ({ ...g, checks: checks.filter((c) => c.group === g.id) }))
  const other = checks.filter((c) => !known.has(c.group))
  if (other.length) out.push({ id: 'other', label: 'Other', checks: other })
  return out.filter((g) => g.checks.length > 0)
}

const MESSAGES: Record<string, string> = {
  no_baseline: 'Generate and download the project once first. An upgrade needs a previous generation to compare against.',
  up_to_date: 'This project already matches the current generator. There is nothing to upgrade.',
  proposal_open: 'An upgrade proposal for this generation is already open. Open it from the list, or dismiss it first.',
  proposal_closed: 'This proposal is already closed, so it cannot be changed again. Reload to see its final state.',
  baseline_unavailable: 'The last generation was made before upgrades existed, so it was not stored. Download the project again to create a baseline.',
}

export function upgradeError(e: unknown, fallback = 'Something went wrong. Try again.'): string {
  if (e instanceof ApiError) return (e.status === 409 && MESSAGES[e.code]) || e.message || fallback
  return e instanceof Error && e.message ? e.message : fallback
}

const isRec = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const str = (v: unknown): string => (typeof v === 'string' ? v : '')

export const readBlockChanges = (v: unknown[]): UpgradeBlockChange[] =>
  v.filter(isRec).map((r) => ({ block: str(r.block), from: typeof r.from === 'string' ? r.from : null, to: typeof r.to === 'string' ? r.to : null, bump: str(r.bump) }))
export const readFiles = (v: unknown[]): UpgradeFile[] => v.filter(isRec).map((r) => ({ path: str(r.path), zone: str(r.zone), change: str(r.change) }))
export const readMigrations = (v: unknown[]): { path: string; change: string }[] => v.filter(isRec).map((r) => ({ path: str(r.path), change: str(r.change) }))
export function readSbom(v: unknown): Required<UpgradeSbomDiff> {
  const r = isRec(v) ? v : {}
  const list = (k: string): UpgradeSbomEntry[] => (Array.isArray(r[k]) ? (r[k] as unknown[]).filter(isRec).map((e) => ({ name: str(e.name), spec: typeof e.spec === 'string' ? e.spec : null, from: typeof e.from === 'string' ? e.from : null, to: typeof e.to === 'string' ? e.to : null })) : [])
  return { added: list('added'), removed: list('removed'), changed: list('changed') }
}

/** Why the server flagged (or did not flag) the proposal as safe to apply by hand quickly. Mirrors the backend rule; nothing applies by itself. */
export function eligibilityReason(eligible: boolean, changes: UpgradeBlockChange[], files: UpgradeFile[], migrations: unknown[], scorecardPassing: boolean | null): string {
  if (eligible) return changes.length ? 'Eligible: every block change is a patch bump, the scorecard passes and no migration is involved.' : 'Eligible: only generated files change, the scorecard passes and no migration is involved.'
  if (migrations.length) return 'Not eligible: the proposal adds or changes a database migration, so review it by hand.'
  if (scorecardPassing === false) return 'Not eligible: the scorecard has a failing check.'
  if (changes.some((c) => c.bump === 'major')) return 'Not eligible: a block changes by a major version.'
  if (changes.some((c) => c.bump !== 'patch')) return 'Not eligible: a block changes by more than a patch version.'
  if (files.some((f) => f.zone !== 'generated')) return 'Not eligible: files outside the generated zone change.'
  return 'Not eligible: the proposal is not a plain patch-level change.'
}

export const patchFilename = (id: string) => `upgrade-${id.slice(0, 8)}.patch`
export const applyCommand = (id: string) => `git apply --3way ${patchFilename(id)}`
export const shortDate = (s: string | null) => (s ? s.slice(0, 10) : '')
