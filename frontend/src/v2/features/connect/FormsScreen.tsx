import { use, useReducer, useState, Suspense } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { defaultFor, validateValue } from '../../../forms/schemaLogic'
import type { JsonSchema, PathErrors } from '../../../forms/types'
import { useT } from '../../i18n'
import { PageHeader } from '../../patterns'
import { SchemaFields } from '../../patterns/SchemaFields'
import { Alert, Button, Card, Checkbox, CodeBlock, EmptyState, ErrorBoundary, Field, Row, Select, Skeleton, Stack, Tabs } from '../../ui'
import { initialSchemaDraft, schemaDraftReducer, shownErrors } from './state/schemaDraft'

const blocks = ['observability', 'lists', 'storage'] as const
const files = import.meta.glob<JsonSchema>('../../../forms/schemas/*.json', { import: 'default' })
const fileIds = Object.keys(files).map(path => path.split('/').at(-1)!.replace('.json', ''))
const schemas = new Map<string, Promise<JsonSchema>>()
const widgets: JsonSchema = {
  type: 'object', title: 'Schema widgets',
  'x-ui': { order: ['notes', 'mode', 'options', 'metadata', 'nested'] },
  properties: {
    hidden_field: { type: 'string', default: 'Present in value', 'x-ui': { hidden: true } },
    notes: { type: 'string', 'x-ui': { widget: 'textarea', help: 'Multiline text.' } },
    mode: { anyOf: [{ type: 'string', enum: ['sample', 'custom'] }, { type: 'null' }] },
    options: { anyOf: [{ type: 'object', properties: { summary: { type: 'string' } } }, { type: 'null' }], 'x-ui': { optional: true } },
    metadata: { type: 'object' },
    nested: { $ref: '#/$defs/example', title: 'Recursive schema' },
  },
  $defs: { example: { type: 'object', properties: { nested: { $ref: '#/$defs/example' } } } },
}

function useSchema(id: string) {
  if (id === 'widgets') return widgets
  const path = '../../../forms/schemas/' + id + '.json'
  let request = schemas.get(id)
  if (!request) {
    request = files[path]()
    schemas.set(id, request)
  }
  return use(request)
}

const sampleErrors: Record<string, PathErrors> = {
  observability: { service_name: ['String should have at most 80 characters'] },
  lists: { 'lists.0.items.0.value': ['String should have at most 80 characters'] },
  storage: { 'security.audit_retention_days': ['Input should be greater than or equal to 1'] },
}

function Preview({ id }: { id: string }) {
  const t = useT()
  const schema = useSchema(id)
  const [readOnly, setReadOnly] = useState(false)
  const [sample, setSample] = useState(false)
  const [state, dispatch] = useReducer(schemaDraftReducer, initialSchemaDraft)
  const base = defaultFor(schema, schema)
  const value = state.draft?.value ?? base
  const hints = validateValue(schema, schema, value)
  const errors = sample ? sampleErrors[id] : undefined
  const errorCount = Object.keys(errors ?? {}).length
  const edit = (path: (string | number)[], next: unknown) => dispatch({ type: 'edit', path, next, base, version: 0 })
  return <Stack>
    <p className="v2-muted">{blocks.some(block => block === id) ? t('connectA2.forms.' + id) : t('connectA2.forms.schemaFile', { id })}</p>
    <Row>
      <Button disabled={!sampleErrors[id]} onClick={() => setSample(true)}>{t('connectA2.forms.showErrors')}</Button>
      <Button disabled={!sample} onClick={() => setSample(false)}>{t('connectA2.forms.clearErrors')}</Button>
      <Checkbox label={t('connectA2.forms.readOnly')} checked={readOnly} onChange={event => setReadOnly(event.target.checked)} />
      <span data-testid="hint-count" aria-live="polite">{t('connectA2.forms.hints', { count: Object.keys(hints).length })}</span>
    </Row>
    {errorCount > 0 && <Alert tone="danger">{t('connectA2.forms.errorCount', { count: errorCount })}</Alert>}
    <Card><Stack><h2>{t('schema.label', { label: schema.title ?? id })}</h2>
      {id === 'lists' && !state.draft && <EmptyState title={t('connectA2.forms.empty')} description={t('connectA2.forms.emptyHelp')} />}
      <SchemaFields schema={schema} value={value} onChange={edit} readOnly={readOnly}
        onBlur={path => dispatch({ type: 'touch', path })} onStructure={path => dispatch({ type: 'structure', path })}
        errors={{ ...shownErrors(state, hints), ...errors }} />
    </Stack></Card>
    <Card><Stack><h2>{t('connectA2.forms.value')}</h2><div data-testid="form-value"><CodeBlock code={JSON.stringify(value, null, 2)} /></div></Stack></Card>
    <Card><Stack><h2>{t('connectA2.forms.renderer')}</h2>
      <ol>{['keyword', 'widget', 'hint', 'backend'].map(key => <li key={key}>{t('connectA2.forms.' + key)}</li>)}</ol>
    </Stack></Card>
  </Stack>
}

export default function FormsScreen() {
  const t = useT()
  const { tab } = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const id = tab && (tab === 'widgets' || fileIds.includes(tab)) ? tab : 'observability'
  const primary = blocks.some(block => block === id)
  const select = (tab: string) => void navigate({ search: previous => ({ ...previous, tab }) })
  const preview = <Stack>
    <Field label={t('connectA2.forms.more')}>{attrs => <Select triggerProps={attrs} value={primary ? '' : id}
      placeholder={t('connectA2.forms.pick')} onValueChange={select} options={[...fileIds.filter(file => !blocks.some(block => block === file)), 'widgets'].map(name =>
        ({ value: name, label: t('connectA2.forms.schemaName', { name: name.replaceAll('-', ' ') }) }))} />}</Field>
    <ErrorBoundary key={id} fallback={() => <Alert tone="danger"
      action={<Button onClick={() => location.reload()}>{t('common.retry')}</Button>}>{t('connectA2.forms.error')}</Alert>}>
      <Suspense fallback={<Card><Skeleton lines={7} /></Card>}><Preview key={id} id={id} /></Suspense>
    </ErrorBoundary>
  </Stack>
  return <Stack>
    <PageHeader title={t('connectA2.forms.title')} description={t('connectA2.forms.intro')} />
    <Tabs label={t('connectA2.forms.tabs')} value={primary ? id : 'more'} onChange={select}
      items={[...blocks, ...(!primary ? ['more'] : [])].map(block => ({
        id: block, label: t('connectA2.forms.tab.' + block), content: preview,
      }))} />
  </Stack>
}
