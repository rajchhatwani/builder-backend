import { useMemo, useState } from 'react'
import { SchemaForm, defaultFor, issuesFromDetail, validateValue, type JsonSchema, type PathErrors } from '../../forms'
import observability from '../../forms/schemas/observability.json'
import lists from '../../forms/schemas/lists.json'
import storage from '../../forms/schemas/storage.json'

/** The three spike blocks: flat toggles/numbers (+ show-when), a list of rows with nested rows, and a nested
 *  object with enums. The schemas are `model_json_schema()` output of the backend models
 *  (regenerate with frontend/scripts/dump_form_schemas.py). */
export const PREVIEW_BLOCKS = [
  {
    id: 'observability', label: 'Observability', shape: 'Flat toggles and numbers, show-when', schema: observability as JsonSchema,
    // What FastAPI answers with 422 for a body that breaks these constraints (text copied from Pydantic).
    sample: [{ loc: ['body', 'service_name'], msg: 'String should have at most 80 characters', type: 'string_too_long' }],
  },
  {
    id: 'lists', label: 'Lists', shape: 'List of rows with a nested list of rows', schema: lists as JsonSchema,
    sample: [{ loc: ['body', 'lists', 0, 'items', 0, 'value'], msg: 'String should have at most 80 characters', type: 'string_too_long' }],
  },
  {
    id: 'storage', label: 'Storage', shape: 'Nested objects, enums, show-when', schema: storage as JsonSchema,
    sample: [{ loc: ['body', 'security', 'audit_retention_days'], msg: 'Input should be greater than or equal to 1', type: 'greater_than_equal' }],
  },
]

export function FormsPreviewPage() {
  const [id, setId] = useState(PREVIEW_BLOCKS[0].id)
  const block = PREVIEW_BLOCKS.find((b) => b.id === id)!
  return (
    <>
      <div className="page-header">
        <div>
          <h1>Forms preview</h1>
          <p>
            Developer preview of forms generated from a JSON Schema. Nothing on this page is saved. The messages shown
            after “Show sample backend errors” are the backend's own text, displayed unchanged.
          </p>
        </div>
      </div>
      <nav aria-label="Preview blocks" className="bh-tabs">
        {PREVIEW_BLOCKS.map((b) => (
          <button key={b.id} className={b.id === id ? '' : 'outline'} aria-pressed={b.id === id} onClick={() => setId(b.id)}>
            {b.label}
          </button>
        ))}
      </nav>
      <Preview key={block.id} block={block} />
    </>
  )
}

function Preview({ block }: { block: (typeof PREVIEW_BLOCKS)[number] }) {
  const [value, setValue] = useState<unknown>(() => defaultFor(block.schema, block.schema))
  const [ext, setExt] = useState<PathErrors>({})
  const [readOnly, setReadOnly] = useState(false)
  const hints = useMemo(() => validateValue(block.schema, block.schema, value), [block.schema, value])
  const hintCount = Object.keys(hints).length
  return (
    <>
      <p className="muted">{block.shape}</p>
      <div className="bh-actions">
        <button className="outline" onClick={() => setExt(issuesFromDetail(block.sample))}>Show sample backend errors</button>
        <button className="outline" onClick={() => setExt({})} disabled={!Object.keys(ext).length}>Clear backend errors</button>
        <label className="bh-check">
          <input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} /> Read only
        </label>
        <small className="muted" data-testid="hint-count">{hintCount} client {hintCount === 1 ? 'hint' : 'hints'}</small>
      </div>
      <SchemaForm schema={block.schema} value={value} onChange={setValue} externalErrors={ext} readOnly={readOnly} idPrefix={`fp-${block.id}`} />
      <h2>Value</h2>
      <pre data-testid="form-value">{JSON.stringify(value, null, 2)}</pre>
    </>
  )
}
