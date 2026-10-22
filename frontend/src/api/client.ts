import type {
  ApiErrorBody,
  Entity,
  EntityUpdate,
  Field,
  FieldInput,
  GenerationSummary,
  OnDelete,
  Page,
  Preview,
  Project,
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
}
