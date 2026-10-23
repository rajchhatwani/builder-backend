import type {
  ApiErrorBody,
  AuthConfig,
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
  ValidationReport,
} from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })

  if (response.status === 204) {
    return undefined as T
  }

  const body = await response.json()
  if (!response.ok) {
    throw new ApiError(response.status, body as ApiErrorBody)
  }
  return body as T
}

export const api = {
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
    const response = await fetch(`${BASE_URL}/projects/${projectId}/generate/download`)
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
}

