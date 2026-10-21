export type DbEngine = 'postgres'

export type FieldType =
  | 'string'
  | 'text'
  | 'integer'
  | 'bigint'
  | 'float'
  | 'decimal'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'uuid'
  | 'json'
  | 'enum'

export type RelationKind = 'one_to_many' | 'many_to_many' | 'one_to_one'

export type OnDelete = 'cascade' | 'set_null' | 'restrict'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Project {
  id: string
  name: string
  slug: string
  description: string | null
  db_engine: DbEngine
  version: number
  created_at: string
  updated_at: string
}

export interface EntityOptions {
  operations: string[]
  filterable: string[]
  sortable: string[]
  searchable: string[]
  default_page_size: number
  max_page_size: number
  soft_delete: boolean
}

export interface Entity {
  id: string
  project_id: string
  name: string
  table_name: string
  plural_path: string
  options: EntityOptions
  created_at: string
  updated_at: string
}

export interface Field {
  id: string
  entity_id: string
  name: string
  type: FieldType
  required: boolean
  unique: boolean
  indexed: boolean
  default: unknown
  max_length: number | null
  min_value: number | null
  max_value: number | null
  enum_values: string[] | null
  position: number
  created_at: string
  updated_at: string
}

export interface Relation {
  id: string
  project_id: string
  kind: RelationKind
  from_entity_id: string
  to_entity_id: string
  from_name: string
  to_name: string
  on_delete: OnDelete
  required: boolean
  created_at: string
  updated_at: string
}

export interface ApiErrorBody {
  code: string
  message: string
  details: unknown[]
}
