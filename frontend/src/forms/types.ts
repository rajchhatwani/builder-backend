/** The subset of JSON Schema (as emitted by Pydantic's model_json_schema) that SchemaForm understands. */
export interface UiHint {
  /** Property order inside an object (properties not listed follow in schema order). */
  order?: string[]
  hidden?: boolean
  /** Show this field only while a sibling property matches. Hidden fields keep their value. */
  showWhen?: { field: string; equals?: unknown; in?: unknown[] }
  /** 'csv' renders an array of strings as one comma-separated text box; 'textarea' a multi-line box. */
  widget?: 'csv' | 'textarea'
  label?: string
  /** Singular name for rows of an array ('List' -> legend 'List 1', button 'Add list'). */
  itemLabel?: string
  help?: string
}

export interface JsonSchema {
  $ref?: string
  $defs?: Record<string, JsonSchema>
  type?: string
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  properties?: Record<string, JsonSchema>
  required?: string[]
  items?: JsonSchema
  anyOf?: JsonSchema[]
  allOf?: JsonSchema[]
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  minLength?: number
  maxLength?: number
  minItems?: number
  maxItems?: number
  pattern?: string
  'x-ui'?: UiHint
}

/** Messages keyed by dotted JSON path: 'roles.upload', 'lists.0.items.2.value'. '' is the whole form. */
export type PathErrors = Record<string, string[]>
