import type { KeycloakConfig, KeycloakWrite, SuiteJoinState, SuiteRef, ValidationIssue } from '../../api/types'

export const SUITE_ID_PATTERN = /^[a-z0-9][a-z0-9-]*$/
export const REALM_PREFIX = 'suite-'
/** A Keycloak realm name is at most 63 characters and carries the prefix. */
export const MAX_SUITE_ID_LENGTH = 63 - REALM_PREFIX.length
export const JOIN_STATES: { value: SuiteJoinState; label: string }[] = [
  { value: 'none', label: 'Not joined yet' },
  { value: 'planned', label: 'Planned' },
  { value: 'joined', label: 'Joined' },
]

export interface SuiteForm {
  enabled: boolean
  suiteId: string
  hubIssuer: string
  joinState: SuiteJoinState
}

export const EMPTY_FORM: SuiteForm = { enabled: false, suiteId: '', hubIssuer: '', joinState: 'none' }

export const suiteRealm = (suiteId: string) => `${REALM_PREFIX}${suiteId.trim()}`

/** The saved suite as form state. */
export function formFromSuite(suite: SuiteRef | null | undefined): SuiteForm {
  if (!suite) return { ...EMPTY_FORM }
  return { enabled: true, suiteId: suite.suite_id, hubIssuer: suite.hub_issuer ?? '', joinState: suite.join_state }
}

/** The PATCH /auth "suite" value for a form: null removes the project from its suite. */
export function suiteFromForm(form: SuiteForm): SuiteRef | null {
  if (!form.enabled) return null
  const hub = form.hubIssuer.trim()
  return { suite_id: form.suiteId.trim(), hub_issuer: hub === '' ? null : hub, join_state: form.joinState }
}

export const patchBody = (form: SuiteForm): { suite: SuiteRef | null } => ({ suite: suiteFromForm(form) })

/** The Keycloak write body that makes the project a shared-mode member of the suite realm. Everything else is kept as loaded. */
export function keycloakBodyForSuite(current: KeycloakConfig, suiteId: string): KeycloakWrite {
  return {
    mode: 'shared',
    realm: suiteRealm(suiteId),
    api_client_id: current.api_client_id,
    web_client_id: current.web_client_id,
    redirect_uris: current.redirect_uris,
    password_min_length: current.password_min_length,
    mfa: current.mfa,
    session_idle_minutes: current.session_idle_minutes,
    session_max_hours: current.session_max_hours,
    audit_retention_days: current.audit_retention_days,
    identity_providers: current.identity_providers,
    source_project_id: null,
  }
}

const isLocalhost = (host: string) => host === 'localhost' || host === '127.0.0.1' || host === '[::1]'

/** Client-side hints only; the server validation is the authority. Returns plain-language messages. */
export function hints(form: SuiteForm): { suiteId: string | null; hubIssuer: string | null } {
  if (!form.enabled) return { suiteId: null, hubIssuer: null }
  const id = form.suiteId.trim()
  let suiteId: string | null = null
  if (id === '') suiteId = 'Enter a suite id.'
  else if (id.length > MAX_SUITE_ID_LENGTH) suiteId = `Use at most ${MAX_SUITE_ID_LENGTH} characters.`
  else if (!SUITE_ID_PATTERN.test(id)) suiteId = 'Use lowercase letters, digits and hyphens, starting with a letter or digit.'
  else if (id.endsWith('-')) suiteId = 'Must not end with a hyphen.'

  const hub = form.hubIssuer.trim()
  let hubIssuer: string | null = null
  if (hub !== '') {
    let url: URL | null = null
    try {
      url = new URL(hub)
    } catch {
      url = null
    }
    if (!url) hubIssuer = 'Enter a full address such as https://id.example.com/realms/suite-acme.'
    else if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLocalhost(url.hostname))) hubIssuer = 'Use https (http is only allowed for localhost).'
    else if (url.search !== '' || url.username !== '' || url.password !== '') hubIssuer = 'Must not contain a query or credentials.'
    else if (suiteId === null && !url.pathname.replace(/\/+$/, '').endsWith(`/realms/${suiteRealm(id)}`)) hubIssuer = `Must end with /realms/${suiteRealm(id)}.`
  }
  return { suiteId, hubIssuer }
}

export const hasHints = (form: SuiteForm) => {
  const h = hints(form)
  return h.suiteId !== null || h.hubIssuer !== null
}

export const isDirty = (form: SuiteForm, saved: SuiteRef | null) => JSON.stringify(patchBody(form).suite) !== JSON.stringify(saved)

/** Validation issues about the suite or the realm it derives (server codes and paths). */
export function suiteIssues(issues: ValidationIssue[]): ValidationIssue[] {
  return issues.filter((i) => i.path.startsWith('auth.suite') || i.code === 'suite_realm_derived' || i.code === 'suite_requires_shared')
}
