import {
  BASE_URL,
  CSRF_HEADERS,
  authHeader,
  notifySessionLost,
  refreshSession,
  setAccessToken,
  type Surface,
} from './session'
import type {
  BehaviorIssues,
  SpecOp,
  ExpressionCheckRead,
  ProjectStatus,
  StateMachinesRead,
  SettingsRead, SettingBody, SequencesRead, SequenceBody, ListsRead, ListBody, HistoryRead, HistoryBody, HooksRead, HookBody, SeedRead, SeedProfileBody,
  AdminInsights,
  ImpersonationDigest,
  ImpersonationSessionRow,
  ImpersonationStarted,
  ImpersonationState,
  AdminOrg,
  AdminOrgMember,
  AdminOrgProject,
  AdminSubscription,
  OrgAuditEntry,
  ReconcileReport,
  Organization,
  OrgInvitation,
  OrgLockedDetail,
  OrgInvitationCreated,
  OrgMember,
  OrgPlan,
  OrgRole,
  PlanInfo,
  PlanWrite,
  QuotaDetail,
  AdminProject,
  AdminStats,
  AdminUser,
  ApiErrorBody,
  LoginDiscovery,
  LoginResult,
  MfaStatus,
  OrgMfaDetail,
  OrgPolicies,
  OrgPoliciesUpdate,
  SessionWithRecoveryCodes,
  ScimConfig,
  ScimConfigUpdate,
  ScimToken,
  SsoCheck,
  SsoConfig,
  SsoConfigWrite,
  SsoDomain,
  TotpSetup,
  ApiTokenCreated,
  ApiTokenInfo,
  ProjectToken,
  AuditEntry,
  Member,
  MemberRole,
  PlatformRole,
  PlatformSettings,
  SessionResponse,
  UserAccount,
  AuthConfig,
  AuthorizationSettings,
  DeploymentPlan,
  DocumentsSettings,
  DocumentsWrite,
  LibraryTemplate,
  DeploymentSettings,
  DeploymentWrite,
  ObservabilitySettings,
  ObservabilityWrite,
  AuthorizationWrite,
  CoverageResult,
  RecommendAnswers,
  Recommendation,
  SimulateRequest,
  SimulateResult,
  SpecForPolicies,
  AuthConfigCreate,
  AuthConfigUpdate,
  AuthCustomField,
  AuthCustomFieldCreate,
  AuthCustomFieldUpdate,
  Entity,
  EntityUpdate,
  Field,
  FieldInput,
  GenerationSummary,
  KeycloakConfig,
  KeycloakImpact,
  KeycloakWrite,
  PaymentsConfig,
  PaymentsImpact,
  PaymentsSizingResult,
  PaymentsWrite,
  StorageConfig,
  StorageImpact,
  StorageWrite,
  OnDelete,
  Page,
  PermissionEntry,
  Preview,
  Project,
  ProjectPermission,
  ProjectRole,
  ProjectRoleCreate,
  ProjectRoleUpdate,
  Relation,
  RelationKind,
  ValidationIssue,
  ValidationReport,
} from './types'
import { isMfaChallenge } from './types'
import type { SpecBlocks } from '../shell/connect/specTypes'

export class ApiError extends Error {
  code: string
  details: unknown[]
  status: number

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.code = body.code
    this.details = body.details
    this.status = status
  }
}

interface RequestOptions {
  surface?: Surface
  /** Sign-in style calls: a 401 means "wrong password", not "session expired". */
  anonymous?: boolean
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options: RequestOptions = {},
  retried = false,
): Promise<T> {
  const surface = options.surface ?? 'app'
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.anonymous ? {} : authHeader(surface)),
      ...init?.headers,
    },
  })

  if (response.status === 401 && !options.anonymous && !retried) {
    if (await refreshSession(surface)) return request<T>(path, init, options, true)
    notifySessionLost(surface)
  }

  if (response.status === 204) {
    return undefined as T
  }

  // A proxy or crashed server can answer with HTML or an empty body: never let a SyntaxError escape.
  let body: unknown
  try {
    body = await response.json()
  } catch {
    if (!response.ok) {
      body = { code: 'bad_response', message: `The server answered ${response.status} without a readable error`, details: [] }
    } else {
      throw new ApiError(response.status, { code: 'bad_response', message: 'The server sent a response that could not be read', details: [] })
    }
  }
  if (!response.ok) {
    const raw = (body ?? {}) as Partial<ApiErrorBody>
    const error = new ApiError(response.status, {
      code: typeof raw.code === 'string' ? raw.code : 'bad_response',
      message: typeof raw.message === 'string' ? raw.message : `The server answered ${response.status}`,
      details: Array.isArray(raw.details) ? raw.details : [],
    })
    if (response.status === 402) notifyQuotaExceeded(error)
    if (response.status === 423 && error.code === 'org_deletion_pending') notifyOrgLocked(error)
    if (response.status === 403 && error.code === 'org_mfa_required') notifyOrgMfaRequired(error)
    throw error
  }
  return body as T
}

// ── 402 Payment Required: a plan cap was hit (seats, projects, tokens) ──────
type QuotaListener = (error: ApiError, detail: QuotaDetail | null) => void
const quotaListeners = new Set<QuotaListener>()

/** Subscribe to quota refusals from any API call. Returns an unsubscribe function. */
export function onQuotaExceeded(listener: QuotaListener): () => void {
  quotaListeners.add(listener)
  return () => {
    quotaListeners.delete(listener)
  }
}

function notifyQuotaExceeded(error: ApiError) {
  const detail = (error.details[0] as QuotaDetail | undefined) ?? null
  quotaListeners.forEach((listener) => listener(error, detail))
}

// ── 423 Locked: the organization is waiting for deletion ───────────────────
type OrgLockedListener = (error: ApiError, detail: OrgLockedDetail | null) => void
const orgLockedListeners = new Set<OrgLockedListener>()

/** Subscribe to "this organization is scheduled for deletion" refusals from any API call. */
export function onOrgLocked(listener: OrgLockedListener): () => void {
  orgLockedListeners.add(listener)
  return () => {
    orgLockedListeners.delete(listener)
  }
}

function notifyOrgLocked(error: ApiError) {
  const detail = (error.details[0] as OrgLockedDetail | undefined) ?? null
  orgLockedListeners.forEach((listener) => listener(error, detail))
}

// ── 403 org_mfa_required: the org requires two-factor and this session has none ──
type OrgMfaListener = (error: ApiError, detail: OrgMfaDetail | null) => void
const orgMfaListeners = new Set<OrgMfaListener>()

/** Subscribe to "this organization requires two-factor authentication" refusals. */
export function onOrgMfaRequired(listener: OrgMfaListener): () => void {
  orgMfaListeners.add(listener)
  return () => {
    orgMfaListeners.delete(listener)
  }
}

function notifyOrgMfaRequired(error: ApiError) {
  const detail = (error.details[0] as OrgMfaDetail | undefined) ?? null
  orgMfaListeners.forEach((listener) => listener(error, detail))
}

const json = (data: unknown) => JSON.stringify(data)
const admin: RequestOptions = { surface: 'admin' }

function queryString(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value))
  })
  return query.toString()
}

/** Remember a fresh access token and return the session it came with. */
function adopt<S extends SessionResponse>(surface: Surface, session: S): S {
  setAccessToken(surface, session.access_token)
  return session
}

/** A password sign-in either opens a session or asks for a second step (§4.4). */
function adoptLogin(surface: Surface, result: LoginResult): LoginResult {
  if (!isMfaChallenge(result)) setAccessToken(surface, result.access_token)
  return result
}

const LOGIN_PREFIX: Record<Surface, string> = { app: '/account/login', admin: '/admin/login' }

/**
 * The second sign-in step, shared by both surfaces. These are sign-in style calls: a 401 means
 * "wrong code" or "step expired", never "refresh the session".
 */
function mfaStep(surface: Surface) {
  const options: RequestOptions = { anonymous: true, surface }
  const prefix = LOGIN_PREFIX[surface]
  return {
    verify: async (mfaToken: string, code: string) =>
      adopt(
        surface,
        await request<SessionResponse>(
          `${prefix}/mfa`,
          { method: 'POST', body: json({ mfa_token: mfaToken, code }) },
          options,
        ),
      ),
    setup: (mfaToken: string) =>
      request<TotpSetup>(`${prefix}/mfa/setup`, { method: 'POST', body: json({ mfa_token: mfaToken }) }, options),
    enable: async (mfaToken: string, code: string) =>
      adopt(
        surface,
        await request<SessionWithRecoveryCodes>(
          `${prefix}/mfa/enable`,
          { method: 'POST', body: json({ mfa_token: mfaToken, code }) },
          options,
        ),
      ),
  }
}

export type MfaStepApi = ReturnType<typeof mfaStep>

function sso(slug: string, path = ''): string {
  return `/orgs/${encodeURIComponent(slug)}/sso${path}`
}

function scim(slug: string, path = ''): string {
  return `/orgs/${encodeURIComponent(slug)}/scim${path}`
}

export const api = {
  // ── Behaviour (read-only in the dashboard so far) ───────────────────────
  getStateMachines: (projectId: string) =>
    request<StateMachinesRead>(`/projects/${projectId}/behavior/state-machines`),
  getProjectStatus: (projectId: string) => request<ProjectStatus>(`/projects/${projectId}/status`),
  /** Read-only live check of a guard expression; `signal` cancels a stale request. */
  checkExpression: (projectId: string, entity: string, expression: string, signal?: AbortSignal) =>
    request<ExpressionCheckRead>(`/projects/${projectId}/behavior/expressions/check`, {
      method: 'POST',
      body: JSON.stringify({ entity, expression, expect: 'bool' }),
      signal,
    }),
  getBehaviorIssues: (projectId: string) =>
    request<BehaviorIssues>(`/projects/${projectId}/behavior/issues`),
  getBehaviorRoles: (projectId: string) => request<{ roles: { name: string; label: string }[] }>(`/projects/${projectId}/behavior/roles`),
  getSettings: (projectId: string) => request<SettingsRead>(`/projects/${projectId}/behavior/settings`),
  putSettings: (projectId: string, settings: SettingBody[], expectedVersion: number) =>
    request<SettingsRead>(`/projects/${projectId}/behavior/settings`, {
      method: 'PUT',
      body: JSON.stringify({ settings, expected_version: expectedVersion }),
    }),
  getSequences: (projectId: string) => request<SequencesRead>(`/projects/${projectId}/behavior/sequences`),
  putSequences: (projectId: string, sequences: SequenceBody[], expectedVersion: number) =>
    request<SequencesRead>(`/projects/${projectId}/behavior/sequences`, {
      method: 'PUT',
      body: JSON.stringify({ sequences, expected_version: expectedVersion }),
    }),
  getLists: (projectId: string) => request<ListsRead>(`/projects/${projectId}/behavior/lists`),
  putLists: (projectId: string, lists: ListBody[], expectedVersion: number) =>
    request<ListsRead>(`/projects/${projectId}/behavior/lists`, {
      method: 'PUT',
      body: JSON.stringify({ lists, expected_version: expectedVersion }),
    }),
  listSpecOps: (projectId: string, limit = 200, offset = 0) =>
    request<Page<SpecOp>>(`/projects/${projectId}/spec/ops?limit=${limit}&offset=${offset}`),
  undoSpec: (projectId: string) => request<SpecOp>(`/projects/${projectId}/spec/undo`, { method: 'POST' }),
  redoSpec: (projectId: string) => request<SpecOp>(`/projects/${projectId}/spec/redo`, { method: 'POST' }),
  restoreSpec: (projectId: string, toSeq: number) =>
    request<SpecOp>(`/projects/${projectId}/spec/restore`, { method: 'POST', body: JSON.stringify({ to_seq: toSeq }) }),
  getHistory: (projectId: string) => request<HistoryRead>(`/projects/${projectId}/behavior/history`),
  putHistory: (projectId: string, history: HistoryBody[], expectedVersion: number) =>
    request<HistoryRead>(`/projects/${projectId}/behavior/history`, {
      method: 'PUT',
      body: JSON.stringify({ history, expected_version: expectedVersion }),
    }),
  getHooks: (projectId: string) => request<HooksRead>(`/projects/${projectId}/behavior/hooks`),
  putHooks: (projectId: string, hooks: HookBody[], expectedVersion: number) =>
    request<HooksRead>(`/projects/${projectId}/behavior/hooks`, {
      method: 'PUT',
      body: JSON.stringify({ hooks, expected_version: expectedVersion }),
    }),
  getSeed: (projectId: string) => request<SeedRead>(`/projects/${projectId}/behavior/seed`),
  putSeed: (projectId: string, seed: SeedProfileBody[], expectedVersion: number) =>
    request<SeedRead>(`/projects/${projectId}/behavior/seed`, {
      method: 'PUT',
      body: JSON.stringify({ seed, expected_version: expectedVersion }),
    }),
  // ── Organizations & plan (customer) ──────────────────────────────────────
  listOrgs: () => request<Page<Organization>>('/orgs'),
  getOrg: (slug: string) => request<Organization>(`/orgs/${encodeURIComponent(slug)}`),
  createOrg: (data: { name: string; slug?: string }) =>
    request<Organization>('/orgs', { method: 'POST', body: json(data) }),
  /** Requests deletion (202): the org locks now and is deleted, with its projects, after the grace period. */
  deleteOrg: (slug: string) =>
    request<Organization>(`/orgs/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
  cancelOrgDeletion: (slug: string) =>
    request<Organization>(`/orgs/${encodeURIComponent(slug)}/deletion/cancel`, { method: 'POST' }),
  orgMembers: (slug: string) => request<Page<OrgMember>>(`/orgs/${encodeURIComponent(slug)}/members`),
  setOrgMemberRole: (slug: string, userId: string, role: OrgRole) =>
    request<OrgMember>(`/orgs/${encodeURIComponent(slug)}/members/${userId}`, {
      method: 'PATCH',
      body: json({ role }),
    }),
  /** Also used to leave an organization (your own user id). */
  removeOrgMember: (slug: string, userId: string) =>
    request<void>(`/orgs/${encodeURIComponent(slug)}/members/${userId}`, { method: 'DELETE' }),
  transferOrgOwnership: (slug: string, toUserId: string) =>
    request<void>(
      `/orgs/${encodeURIComponent(slug)}/transfer?${queryString({ to_user_id: toUserId })}`,
      { method: 'POST' },
    ),
  orgInvitations: (slug: string) =>
    request<Page<OrgInvitation>>(`/orgs/${encodeURIComponent(slug)}/invitations`),
  createOrgInvitation: (slug: string, email: string, role: OrgRole) =>
    request<OrgInvitationCreated>(`/orgs/${encodeURIComponent(slug)}/invitations`, {
      method: 'POST',
      body: json({ email, role }),
    }),
  revokeOrgInvitation: (slug: string, id: string) =>
    request<void>(`/orgs/${encodeURIComponent(slug)}/invitations/${id}`, { method: 'DELETE' }),
  myPendingInvitations: () => request<Page<OrgInvitation>>('/orgs/invitations/pending'),
  acceptInvitation: (token: string) =>
    request<Organization>('/orgs/invitations/accept', { method: 'POST', body: json({ token }) }),
  /** Accept one of my pending invites without the link (the signed-in address is the proof). */
  acceptInvitationById: (id: string) =>
    request<Organization>(`/orgs/invitations/${id}/accept`, { method: 'POST' }),
  resendOrgInvitation: (slug: string, id: string) =>
    request<OrgInvitationCreated>(`/orgs/${encodeURIComponent(slug)}/invitations/${id}/resend`, {
      method: 'POST',
    }),
  renameOrg: (slug: string, name: string) =>
    request<Organization>(`/orgs/${encodeURIComponent(slug)}`, { method: 'PATCH', body: json({ name }) }),
  joinOrgProject: (slug: string, projectId: string, role: 'owner' | 'editor' | 'viewer' = 'editor') =>
    request<{ project_id: string; role: string }>(
      `/orgs/${encodeURIComponent(slug)}/projects/${projectId}/join`,
      { method: 'POST', body: json({ role }) },
    ),
  transferOrgProject: (slug: string, projectId: string, toSlug: string) =>
    request<Project>(`/orgs/${encodeURIComponent(slug)}/projects/${projectId}/transfer`, {
      method: 'POST',
      body: json({ to_slug: toSlug }),
    }),
  orgAudit: (slug: string, limit = 50, offset = 0) =>
    request<Page<OrgAuditEntry>>(
      `/orgs/${encodeURIComponent(slug)}/audit?${queryString({ limit, offset })}`,
    ),
  setDefaultOrg: (organizationId: string) =>
    request<UserAccount>('/account/me/default-organization', {
      method: 'PUT',
      body: json({ organization_id: organizationId }),
    }),
  orgProjects: (slug: string) => request<Page<Project>>(`/orgs/${encodeURIComponent(slug)}/projects`),
  orgPlan: (slug: string) => request<OrgPlan>(`/orgs/${encodeURIComponent(slug)}/plan`),

  // ── "View as" banner side (§4.5): only a viewing token has any of this ─────
  impersonationState: () => request<ImpersonationState>('/account/impersonation'),
  setImpersonationWrites: (enabled: boolean) =>
    request<ImpersonationState>('/account/impersonation/writes', {
      method: 'POST',
      body: json({ enabled }),
    }),
  endImpersonation: () => request<void>('/account/impersonation/end', { method: 'POST' }),
  /** The viewing tab learns who it is from the token it was handed; there is no refresh cookie. */
  me: () => request<UserAccount>('/account/me'),

  // ── Org data export (§9): the file the owner downloads ────────────────────
  async exportOrg(slug: string): Promise<{ blob: Blob; filename: string }> {
    const response = await fetch(`${BASE_URL}/orgs/${encodeURIComponent(slug)}/export`, {
      credentials: 'include',
      headers: authHeader('app'),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as ApiErrorBody | null
      throw new ApiError(response.status, body ?? { code: 'http_error', message: 'Export failed', details: [] })
    }
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `${slug}-export.json`
    return { blob: await response.blob(), filename }
  },

  // ── Org security policies (§8) ───────────────────────────────────────────
  orgPolicies: (slug: string) => request<OrgPolicies>(`/orgs/${encodeURIComponent(slug)}/policies`),
  updateOrgPolicies: (slug: string, data: OrgPoliciesUpdate) =>
    request<OrgPolicies>(`/orgs/${encodeURIComponent(slug)}/policies`, {
      method: 'PATCH',
      body: json(data),
    }),

  // ── Org single sign-on (§4.2, §12.D) — session only ──────────────────────
  ssoConfig: (slug: string) => request<SsoConfig>(sso(slug)),
  saveSsoConfig: (slug: string, data: SsoConfigWrite) =>
    request<SsoConfig>(sso(slug), { method: 'PUT', body: json(data) }),
  deleteSsoConfig: (slug: string) => request<void>(sso(slug), { method: 'DELETE' }),
  activateSso: (slug: string, on: boolean) =>
    request<SsoConfig>(sso(slug, on ? '/activate' : '/deactivate'), { method: 'POST' }),
  addSsoDomain: (slug: string, domain: string) =>
    request<SsoDomain>(sso(slug, '/domains'), { method: 'POST', body: json({ domain }) }),
  verifySsoDomain: (slug: string, domain: string) =>
    request<SsoDomain>(sso(slug, `/domains/${encodeURIComponent(domain)}/verify`), { method: 'POST' }),
  removeSsoDomain: (slug: string, domain: string) =>
    request<void>(sso(slug, `/domains/${encodeURIComponent(domain)}`), { method: 'DELETE' }),
  /** "Test with my own e-mail": a login URL to open; the result comes back in the hash. */
  startSsoTest: (slug: string) =>
    request<{ login_url: string; expires_in: number }>(sso(slug, '/test'), { method: 'POST' }),
  checkSso: (slug: string) => request<SsoCheck>(sso(slug, '/check'), { method: 'POST' }),

  // ── Org SCIM provisioning (§4.3, §12.E.5) — admins, session only ─────────
  scimConfig: (slug: string) => request<ScimConfig>(scim(slug)),
  /** Creates the directory (switched on) or rotates its token; the old token stops at once. */
  issueScimToken: (slug: string) => request<ScimToken>(scim(slug, '/token'), { method: 'POST' }),
  /** `group_roles` replaces the whole dictionary. */
  updateScim: (slug: string, data: ScimConfigUpdate) =>
    request<ScimConfig>(scim(slug), { method: 'PATCH', body: json(data) }),
  /** Removes the directory and its user/group records; org memberships stay. */
  deleteScim: (slug: string) => request<void>(scim(slug), { method: 'DELETE' }),
  startCheckout: (slug: string, planId: string) =>
    request<{ id: string; url: string }>(`/orgs/${encodeURIComponent(slug)}/billing/checkout`, {
      method: 'POST',
      body: json({ plan_id: planId }),
    }),
  /** Stripe Billing Portal for an org that already pays: plan change, card, cancel. */
  openBillingPortal: (slug: string) =>
    request<{ url: string }>(`/orgs/${encodeURIComponent(slug)}/billing/portal`, { method: 'POST' }),

  listProjects: (limit = 50, offset = 0) =>
    request<Page<Project>>(`/projects?limit=${limit}&offset=${offset}`),
  createProject: (data: { name: string; slug?: string; description?: string; organization_id?: string }) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),

  listEntities: (projectId: string, limit = 50, offset = 0) =>
    request<Page<Entity>>(`/projects/${projectId}/entities?limit=${limit}&offset=${offset}`),
  createEntity: (projectId: string, data: { name: string }) =>
    request<Entity>(`/projects/${projectId}/entities`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateEntity: (id: string, data: EntityUpdate) =>
    request<Entity>(`/entities/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteEntity: (id: string) => request<void>(`/entities/${id}`, { method: 'DELETE' }),

  listFields: (entityId: string, limit = 50, offset = 0) =>
    request<Page<Field>>(`/entities/${entityId}/fields?limit=${limit}&offset=${offset}`),
  createField: (entityId: string, data: FieldInput) =>
    request<Field>(`/entities/${entityId}/fields`, { method: 'POST', body: JSON.stringify(data) }),
  updateField: (id: string, data: Partial<FieldInput>) =>
    request<Field>(`/fields/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteField: (id: string) => request<void>(`/fields/${id}`, { method: 'DELETE' }),

  listRelations: (projectId: string, limit = 50, offset = 0) =>
    request<Page<Relation>>(`/projects/${projectId}/relations?limit=${limit}&offset=${offset}`),
  createRelation: (
    projectId: string,
    data: {
      kind: RelationKind
      from_entity_id: string
      to_entity_id: string
      from_name: string
      to_name: string
      on_delete?: OnDelete
      required?: boolean
    },
  ) =>
    request<Relation>(`/projects/${projectId}/relations`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteRelation: (id: string) => request<void>(`/relations/${id}`, { method: 'DELETE' }),

  validateProject: (projectId: string) =>
    request<ValidationReport>(`/projects/${projectId}/validate`, { method: 'POST' }),
  previewGeneration: (projectId: string) =>
    request<Preview>(`/projects/${projectId}/generate/preview`, { method: 'POST' }),
  listGenerations: (projectId: string, limit = 20, offset = 0) =>
    request<Page<GenerationSummary>>(
      `/projects/${projectId}/generations?limit=${limit}&offset=${offset}`,
    ),

  /** Downloads the generated project zip and records a generation. */
  async downloadZip(projectId: string, fallbackName: string): Promise<{ blob: Blob; filename: string }> {
    const download = () =>
      fetch(`${BASE_URL}/projects/${projectId}/generate/download`, {
        credentials: 'include',
        headers: authHeader('app'),
      })
    let response = await download()
    if (response.status === 401 && (await refreshSession('app'))) response = await download()
    if (!response.ok) {
      throw new ApiError(response.status, (await response.json().catch(() => null)) ?? { code: 'bad_response', message: 'Download failed', details: [] })
    }
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const match = /filename="([^"]+)"/.exec(disposition)
    return { blob: await response.blob(), filename: match?.[1] ?? fallbackName }
  },

  // ── Auth Config ──────────────────────────────────────────────────────────

  getKeycloak: (projectId: string) => request<KeycloakConfig>(`/projects/${projectId}/keycloak`),
  putKeycloak: (projectId: string, data: KeycloakWrite) =>
    request<KeycloakConfig>(`/projects/${projectId}/keycloak`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  keycloakImpact: (projectId: string, action: 'enable' | 'disable') =>
    request<KeycloakImpact>(`/projects/${projectId}/keycloak/impact?action=${action}`),
  switchKeycloak: (projectId: string, action: 'enable' | 'disable') =>
    request<KeycloakConfig>(`/projects/${projectId}/keycloak/${action}`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true }),
    }),

  getPayments: (projectId: string) => request<PaymentsConfig>(`/projects/${projectId}/payments`),
  putPayments: (projectId: string, data: PaymentsWrite) =>
    request<PaymentsConfig>(`/projects/${projectId}/payments`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  paymentsSizing: (projectId: string) =>
    request<PaymentsSizingResult>(`/projects/${projectId}/payments/sizing`),
  paymentsImpact: (projectId: string, action: 'enable' | 'disable') =>
    request<PaymentsImpact>(`/projects/${projectId}/payments/impact?action=${action}`),
  switchPayments: (projectId: string, action: 'enable' | 'disable') =>
    request<PaymentsConfig>(`/projects/${projectId}/payments/${action}`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true }),
    }),

  getStorage: (projectId: string) => request<StorageConfig>(`/projects/${projectId}/storage`),
  putStorage: (projectId: string, data: StorageWrite) =>
    request<StorageConfig>(`/projects/${projectId}/storage`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  storageImpact: (projectId: string, action: 'enable' | 'disable') =>
    request<StorageImpact>(`/projects/${projectId}/storage/impact?action=${action}`),
  switchStorage: (projectId: string, action: 'enable' | 'disable') =>
    request<StorageConfig>(`/projects/${projectId}/storage/${action}`, {
      method: 'POST',
      body: JSON.stringify({ confirm: true }),
    }),

  getDocuments: (projectId: string) =>
    request<DocumentsSettings>(`/projects/${projectId}/documents`),
  putDocuments: (projectId: string, data: DocumentsWrite) =>
    request<DocumentsSettings>(`/projects/${projectId}/documents`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  documentsIssues: (projectId: string) =>
    request<{ issues: ValidationIssue[] }>(`/projects/${projectId}/documents/issues`),
  documentsLibrary: (projectId: string) =>
    request<LibraryTemplate[]>(`/projects/${projectId}/documents/library`),
  /** The PDF the generated API would render for this template and data. */
  previewDocument: async (
    projectId: string,
    data: { template: Record<string, unknown>; data: Record<string, unknown>; compute: string | null },
  ): Promise<Blob> => {
    const response = await fetch(`${BASE_URL}/projects/${projectId}/documents/preview`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeader('app') },
      body: JSON.stringify(data),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => ({ message: 'Preview failed' }))) as ApiErrorBody
      throw new ApiError(response.status, body)
    }
    return response.blob()
  },

  getDeployment: (projectId: string) =>
    request<DeploymentSettings>(`/projects/${projectId}/deployment`),
  putDeployment: (projectId: string, data: DeploymentWrite) =>
    request<DeploymentSettings>(`/projects/${projectId}/deployment`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deploymentIssues: (projectId: string) =>
    request<{ issues: ValidationIssue[] }>(`/projects/${projectId}/deployment/issues`),
  deploymentPlan: (projectId: string, data: DeploymentWrite) =>
    request<DeploymentPlan>(`/projects/${projectId}/deployment/plan`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getObservability: (projectId: string) =>
    request<ObservabilitySettings>(`/projects/${projectId}/observability`),
  putObservability: (projectId: string, data: ObservabilityWrite) =>
    request<ObservabilitySettings>(`/projects/${projectId}/observability`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  observabilityIssues: (projectId: string) =>
    request<{ issues: ValidationIssue[] }>(`/projects/${projectId}/observability/issues`),

  getAuthorization: (projectId: string) =>
    request<AuthorizationSettings>(`/projects/${projectId}/authorization`),
  putAuthorization: (projectId: string, data: AuthorizationWrite) =>
    request<AuthorizationSettings>(`/projects/${projectId}/authorization`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  authorizationIssues: (projectId: string) =>
    request<{ issues: ValidationIssue[] }>(`/projects/${projectId}/authorization/issues`),
  simulateAuthorization: (projectId: string, data: SimulateRequest) =>
    request<SimulateResult>(`/projects/${projectId}/authorization/simulate`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  authorizationCoverage: (projectId: string) =>
    request<CoverageResult>(`/projects/${projectId}/authorization/coverage`),
  recommendFromProject: (projectId: string) =>
    request<Recommendation>(`/projects/${projectId}/authorization/recommendation`),
  recommendAuthorization: (projectId: string, data: RecommendAnswers) =>
    request<Recommendation>(`/projects/${projectId}/authorization/recommend`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  /** The whole assembled spec as loose JSON (F2-6 reads only its `notifications` block). */
  getSpecJson: (projectId: string) => request<Record<string, unknown>>(`/projects/${projectId}/spec`),
  getSpecForPolicies: (projectId: string) =>
    request<SpecForPolicies>(`/projects/${projectId}/spec`),
  /** The spec blocks the Connect/Operate pages show read-only (webhooks, providers, jobs, workflows). */
  getSpecBlocks: (projectId: string) => request<SpecBlocks>(`/projects/${projectId}/spec`),

  getAuthConfig: (projectId: string) =>
    request<AuthConfig>(`/projects/${projectId}/auth`),
  createAuthConfig: (projectId: string, data: AuthConfigCreate) =>
    request<AuthConfig>(`/projects/${projectId}/auth`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateAuthConfig: (projectId: string, data: AuthConfigUpdate) =>
    request<AuthConfig>(`/projects/${projectId}/auth`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  // ── Roles ────────────────────────────────────────────────────────────────

  listRoles: (projectId: string, limit = 50, offset = 0) =>
    request<Page<ProjectRole>>(`/projects/${projectId}/roles?limit=${limit}&offset=${offset}`),
  createRole: (projectId: string, data: ProjectRoleCreate) =>
    request<ProjectRole>(`/projects/${projectId}/roles`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getRole: (roleId: string) => request<ProjectRole>(`/roles/${roleId}`),
  updateRole: (roleId: string, data: ProjectRoleUpdate) =>
    request<ProjectRole>(`/roles/${roleId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteRole: (roleId: string) => request<void>(`/roles/${roleId}`, { method: 'DELETE' }),

  // ── Permissions ──────────────────────────────────────────────────────────

  listPermissions: (projectId: string, limit = 200, offset = 0) =>
    request<Page<ProjectPermission>>(
      `/projects/${projectId}/permissions?limit=${limit}&offset=${offset}`,
    ),
  /** Every permission of a project, fetched page by page (the API caps a page at 200). */
  async listAllPermissions(projectId: string): Promise<ProjectPermission[]> {
    const all: ProjectPermission[] = []
    for (let offset = 0; ; offset += 200) {
      const page = await api.listPermissions(projectId, 200, offset)
      all.push(...page.items)
      if (all.length >= page.total || page.items.length === 0) return all
    }
  },
  bulkUpsertPermissions: (projectId: string, permissions: PermissionEntry[]) =>
    request<ProjectPermission[]>(`/projects/${projectId}/permissions`, {
      method: 'POST',
      body: JSON.stringify({ permissions }),
    }),
  deletePermission: (permissionId: string) =>
    request<void>(`/permissions/${permissionId}`, { method: 'DELETE' }),

  // ── Auth Custom Fields ───────────────────────────────────────────────────

  listAuthCustomFields: (projectId: string, limit = 50, offset = 0) =>
    request<Page<AuthCustomField>>(
      `/projects/${projectId}/auth/custom-fields?limit=${limit}&offset=${offset}`,
    ),
  createAuthCustomField: (projectId: string, data: AuthCustomFieldCreate) =>
    request<AuthCustomField>(`/projects/${projectId}/auth/custom-fields`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateAuthCustomField: (fieldId: string, data: AuthCustomFieldUpdate) =>
    request<AuthCustomField>(`/auth/custom-fields/${fieldId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteAuthCustomField: (fieldId: string) =>
    request<void>(`/auth/custom-fields/${fieldId}`, { method: 'DELETE' }),

  // ── Accounts ─────────────────────────────────────────────────────────────

  register: async (data: { email: string; password: string; name?: string }) =>
    adopt(
      'app',
      await request<SessionResponse>(
        '/account/register',
        { method: 'POST', body: json(data) },
        { anonymous: true },
      ),
    ),
  login: async (email: string, password: string) =>
    adoptLogin(
      'app',
      await request<LoginResult>(
        '/account/login',
        { method: 'POST', body: json({ email, password }) },
        { anonymous: true },
      ),
    ),
  /** Email first (§4.2): an address on a domain with active SSO goes to the org's IdP. */
  discoverLogin: (email: string) =>
    request<LoginDiscovery>(
      '/account/login/discover',
      { method: 'POST', body: json({ email }) },
      { anonymous: true },
    ),
  loginMfa: mfaStep('app'),

  // ── Two-factor authentication (signed in) ────────────────────────────────
  // Wrong password / code answer 422 here (not 401), so the session stays.
  mfaStatus: () => request<MfaStatus>('/account/mfa'),
  totpSetup: (password: string) =>
    request<TotpSetup>('/account/mfa/totp/setup', { method: 'POST', body: json({ password }) }),
  /** Returns a fresh session that counts as MFA'd, plus the recovery codes (shown once). */
  totpEnable: async (code: string) =>
    adopt(
      'app',
      await request<SessionWithRecoveryCodes>('/account/mfa/totp/enable', {
        method: 'POST',
        body: json({ code }),
      }),
    ),
  totpDisable: (password: string, code: string) =>
    request<void>('/account/mfa/totp/disable', { method: 'POST', body: json({ password, code }) }),
  regenerateRecoveryCodes: (code: string) =>
    request<{ recovery_codes: string[] }>('/account/mfa/recovery-codes', {
      method: 'POST',
      body: json({ code }),
    }),
  /** Try to resume a session from the refresh cookie (page load). Null if there is none. */
  async resume(): Promise<UserAccount | null> {
    if (!(await refreshSession('app'))) return null
    try {
      return await request<UserAccount>('/account/me')
    } catch {
      return null
    }
  },
  async logout() {
    try {
      await request<void>(
        '/account/logout',
        { method: 'POST', headers: CSRF_HEADERS },
        { anonymous: true },
      )
    } finally {
      setAccessToken('app', null)
    }
  },
  logoutEverywhere: async () => {
    await request<void>('/account/logout-all', { method: 'POST' })
    setAccessToken('app', null)
  },
  changePassword: async (current_password: string, new_password: string) =>
    adopt(
      'app',
      await request<SessionResponse>('/account/password', {
        method: 'POST',
        body: json({ current_password, new_password }),
      }),
    ),
  listApiTokens: () => request<ApiTokenInfo[]>('/account/tokens'),
  createApiToken: (data: {
    name: string
    description?: string | null
    scopes: string[]
    expires_in_days: number
    project_id?: string | null
  }) => request<ApiTokenCreated>('/account/tokens', { method: 'POST', body: json(data) }),
  revokeApiToken: (id: string) => request<void>(`/account/tokens/${id}`, { method: 'DELETE' }),

  // ── Project-scoped tokens (owners only) ──────────────────────────────────
  listProjectTokens: (projectId: string) =>
    request<ProjectToken[]>(`/projects/${projectId}/tokens`),
  revokeProjectToken: (projectId: string, tokenId: string) =>
    request<void>(`/projects/${projectId}/tokens/${tokenId}`, { method: 'DELETE' }),

  // ── Project members ──────────────────────────────────────────────────────

  listMembers: (projectId: string) => request<Member[]>(`/projects/${projectId}/members`),
  addMember: (projectId: string, email: string, role: MemberRole) =>
    request<Member>(`/projects/${projectId}/members`, {
      method: 'POST',
      body: json({ email, role }),
    }),
  setMemberRole: (projectId: string, userId: string, role: MemberRole) =>
    request<Member>(`/projects/${projectId}/members/${userId}`, {
      method: 'PATCH',
      body: json({ role }),
    }),
  /** Owner-only: grant or revoke a member's MCP access. */
  setMemberMcp: (projectId: string, userId: string, mcp_enabled: boolean) =>
    request<Member>(`/projects/${projectId}/members/${userId}/mcp`, {
      method: 'PATCH',
      body: json({ mcp_enabled }),
    }),
  removeMember: (projectId: string, userId: string) =>
    request<void>(`/projects/${projectId}/members/${userId}`, { method: 'DELETE' }),

  // ── Admin console (a separate surface with its own tokens) ───────────────

  adminLogin: async (email: string, password: string) =>
    adoptLogin(
      'admin',
      await request<LoginResult>(
        '/admin/login',
        { method: 'POST', body: json({ email, password }) },
        { anonymous: true, surface: 'admin' },
      ),
    ),
  adminLoginMfa: mfaStep('admin'),
  async adminResume(): Promise<UserAccount | null> {
    if (!(await refreshSession('admin'))) return null
    try {
      return await request<UserAccount>('/admin/me', undefined, admin)
    } catch {
      return null
    }
  },
  async adminLogout() {
    try {
      await request<void>(
        '/admin/logout',
        { method: 'POST', headers: CSRF_HEADERS },
        { anonymous: true, surface: 'admin' },
      )
    } finally {
      setAccessToken('admin', null)
    }
  },
  adminStats: () => request<AdminStats>('/admin/stats', undefined, admin),
  adminSettings: () => request<PlatformSettings>('/admin/settings', undefined, admin),
  adminUsers: (params: {
    q?: string
    status?: string
    role?: string
    limit?: number
    offset?: number
  }) => request<Page<AdminUser>>(`/admin/users?${queryString(params)}`, undefined, admin),
  adminCreateUser: (data: {
    email: string
    name?: string
    platform_role: PlatformRole
    password?: string
  }) =>
    request<{ user: AdminUser; temporary_password: string | null }>(
      '/admin/users',
      { method: 'POST', body: json(data) },
      admin,
    ),
  adminUpdateUser: (
    id: string,
    data: { name?: string; status?: 'active' | 'suspended'; platform_role?: PlatformRole },
  ) => request<AdminUser>(`/admin/users/${id}`, { method: 'PATCH', body: json(data) }, admin),
  adminRevokeSessions: (id: string) =>
    request<void>(`/admin/users/${id}/revoke-sessions`, { method: 'POST' }, admin),
  adminResetPassword: (id: string) =>
    request<{ temporary_password: string }>(
      `/admin/users/${id}/reset-password`,
      { method: 'POST' },
      admin,
    ),
  /** Platform admins only; ends the person's sessions. Refused for your own account. */
  adminResetMfa: (id: string, reason: string) =>
    request<AdminUser>(`/admin/users/${id}/reset-mfa`, { method: 'POST', body: json({ reason }) }, admin),
  /** Configuration check of the org's SSO (operators can't sign in at a customer's IdP). */
  adminCheckSso: (id: string) =>
    request<SsoCheck>(`/admin/organizations/${id}/sso/check`, { method: 'POST' }, admin),
  /** Platform admins only. The new token is shown to nobody (§7.1); SCIM is off until the org issues one. */
  adminRotateScim: (id: string, reason: string) =>
    request<AdminOrg>(`/admin/organizations/${id}/scim/rotate`, { method: 'POST', body: json({ reason }) }, admin),
  adminProjects: (q = '', limit = 50, offset = 0) =>
    request<Page<AdminProject>>(
      `/admin/projects?${queryString({ q, limit, offset })}`,
      undefined,
      admin,
    ),
  adminAudit: (params: {
    action?: string
    organization_id?: string
    actor_id?: string
    since?: string
    result?: string
    via?: string
    limit?: number
    offset?: number
  }) => request<Page<AuditEntry>>(`/admin/audit?${queryString(params)}`, undefined, admin),

  // ── Admin: organizations (seat / project overrides, §6.5) ────────────────
  adminOrganizations: (q = '', limit = 25, offset = 0) =>
    request<Page<AdminOrg>>(
      `/admin/organizations?${queryString({ q, limit, offset })}`,
      undefined,
      admin,
    ),
  adminSetOrgOverrides: (
    id: string,
    data: { seat_override: number | null; project_override: number | null; reason: string },
  ) =>
    request<AdminOrg>(
      `/admin/organizations/${id}/overrides`,
      { method: 'PATCH', body: json(data) },
      admin,
    ),

  adminRescheduleOrgDeletion: (id: string, graceDays: number, reason: string) =>
    request<AdminOrg>(
      `/admin/organizations/${id}/deletion`,
      { method: 'PATCH', body: json({ grace_days: graceDays, reason }) },
      admin,
    ),
  adminExecuteOrgDeletion: (id: string, reason: string) =>
    request<AdminOrg>(
      `/admin/organizations/${id}/deletion/execute`,
      { method: 'POST', body: json({ reason }) },
      admin,
    ),
  adminOrganization: (id: string) =>
    request<AdminOrg>(`/admin/organizations/${id}`, undefined, admin),
  /** §4.5: mint a ten-minute "view as" token. Platform admins only; needs the org's consent. */
  adminImpersonate: (orgId: string, userId: string, reason: string) =>
    request<ImpersonationStarted>(
      `/admin/organizations/${orgId}/members/${userId}/impersonate`,
      { method: 'POST', body: json({ reason }) },
      admin,
    ),
  adminImpersonationSessions: (params: { organization_id?: string; limit?: number; offset?: number }) =>
    request<Page<ImpersonationSessionRow>>(
      `/admin/impersonation/sessions?${queryString(params)}`,
      undefined,
      admin,
    ),
  /** What the daily support-access digest would say (nothing is sent). Platform admins only. */
  adminImpersonationDigest: (hours = 24) =>
    request<ImpersonationDigest>(`/admin/impersonation/digest?hours=${hours}`, undefined, admin),
  adminEndImpersonation: (sessionId: string) =>
    request<void>(`/admin/impersonation/sessions/${sessionId}/end`, { method: 'POST' }, admin),
  adminOrgMembers: (id: string) =>
    request<AdminOrgMember[]>(`/admin/organizations/${id}/members`, undefined, admin),
  adminOrgProjects: (id: string) =>
    request<AdminOrgProject[]>(`/admin/organizations/${id}/projects`, undefined, admin),
  adminSubscriptions: (params: { status?: string; q?: string; limit?: number; offset?: number }) =>
    request<Page<AdminSubscription>>(`/admin/subscriptions?${queryString(params)}`, undefined, admin),
  adminInsights: () => request<AdminInsights>('/admin/insights', undefined, admin),
  adminReconcileBilling: () =>
    request<ReconcileReport>('/admin/billing/reconcile', { method: 'POST' }, admin),
  /** Manual plan change for orgs not billed through Stripe; needs a reason (§6.5). */
  adminSetOrgPlan: (id: string, planId: string, reason: string) =>
    request<AdminOrg>(
      `/admin/organizations/${id}/plan`,
      { method: 'PATCH', body: json({ plan_id: planId, reason }) },
      admin,
    ),

  // ── Admin: plan catalog (§7 Plans tab) ───────────────────────────────────
  adminPlans: () => request<PlanInfo[]>('/admin/plans', undefined, admin),
  adminSavePlan: (id: string, data: PlanWrite) =>
    request<PlanInfo>(`/admin/plans/${encodeURIComponent(id)}`, { method: 'PUT', body: json(data) }, admin),

  // ── Admin: tokens of any user ────────────────────────────────────────────
  adminListUserTokens: (userId: string) =>
    request<ApiTokenInfo[]>(`/admin/users/${userId}/tokens`, undefined, admin),
  adminRevokeUserToken: (userId: string, tokenId: string) =>
    request<void>(`/admin/users/${userId}/tokens/${tokenId}`, { method: 'DELETE' }, admin),
}
