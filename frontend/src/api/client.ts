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
  AdminOrg,
  Organization,
  OrgPlan,
  QuotaDetail,
  AdminProject,
  AdminStats,
  AdminUser,
  ApiErrorBody,
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

  const body = await response.json()
  if (!response.ok) {
    const error = new ApiError(response.status, body as ApiErrorBody)
    if (response.status === 402) notifyQuotaExceeded(error)
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
function adopt(surface: Surface, session: SessionResponse): SessionResponse {
  setAccessToken(surface, session.access_token)
  return session
}

export const api = {
  // ── Organizations & plan (customer) ──────────────────────────────────────
  listOrgs: () => request<Page<Organization>>('/orgs'),
  orgPlan: (slug: string) => request<OrgPlan>(`/orgs/${encodeURIComponent(slug)}/plan`),
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
  createProject: (data: { name: string; slug?: string; description?: string }) =>
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
      throw new ApiError(response.status, (await response.json()) as ApiErrorBody)
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
  getSpecForPolicies: (projectId: string) =>
    request<SpecForPolicies>(`/projects/${projectId}/spec`),

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
    adopt(
      'app',
      await request<SessionResponse>(
        '/account/login',
        { method: 'POST', body: json({ email, password }) },
        { anonymous: true },
      ),
    ),
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
    adopt(
      'admin',
      await request<SessionResponse>(
        '/admin/login',
        { method: 'POST', body: json({ email, password }) },
        { anonymous: true, surface: 'admin' },
      ),
    ),
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
  adminProjects: (q = '', limit = 50, offset = 0) =>
    request<Page<AdminProject>>(
      `/admin/projects?${queryString({ q, limit, offset })}`,
      undefined,
      admin,
    ),
  adminAudit: (params: {
    action?: string
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

  // ── Admin: tokens of any user ────────────────────────────────────────────
  adminListUserTokens: (userId: string) =>
    request<ApiTokenInfo[]>(`/admin/users/${userId}/tokens`, undefined, admin),
  adminRevokeUserToken: (userId: string, tokenId: string) =>
    request<void>(`/admin/users/${userId}/tokens/${tokenId}`, { method: 'DELETE' }, admin),
}
