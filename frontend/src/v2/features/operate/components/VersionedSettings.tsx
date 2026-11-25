import { useReducer } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { validateValue } from '../../../../forms/schemaLogic'
import type { Path } from '../../../../forms/schemaLogic'
import type { JsonSchema, PathErrors } from '../../../../forms/types'
import { useT } from '../../../i18n'
import { ConflictBanner, SaveBar } from '../../../patterns'
import { SchemaFields } from '../../../patterns/SchemaFields'
import type { SchemaFieldOverride } from '../../../patterns/SchemaFields'
import { initialSchemaDraft, schemaDraftReducer, shownErrors } from '../../../patterns/schemaDraft'
import { Alert, Button, Card, Stack } from '../../../ui'
import type { SelectOption } from '../../../ui'
import { errorInfo, fieldErrors } from '../api/operate'
import { LoadState, useOperateDate } from './Common'

type Value = Record<string, unknown>
type SettingsProps = {
  title: string
  schema: JsonSchema
  base: Value
  version: number
  updatedAt: string | null
  readOnly: boolean
  pending: boolean
  saved: boolean
  error: unknown
  reload: () => Promise<boolean>
  save: (value: Value, version: number) => Promise<unknown>
  validate: (value: Value) => PathErrors
  prefix?: string
  loadError?: unknown
  options?: (path: Path, value: Value) => SelectOption[] | undefined
  fieldOverride?: (field: SchemaFieldOverride, touch: () => void) => ReactNode
  children?: (value: Value, focus: () => void) => ReactNode
  aside?: (value: Value) => ReactNode
}

export function VersionedSettings(props: SettingsProps) {
  const { schema, base, version, readOnly, pending, reload } = props
  const t = useT()
  const date = useOperateDate()
  const [draft, dispatch] = useReducer(schemaDraftReducer, initialSchemaDraft)
  const current = (draft.draft?.value ?? base) as Value
  const errors = { ...validateValue(schema, schema, current), ...props.validate(current) }
  const status = errorInfo(props.error)?.status
  const conflict = status === 409
  const formId = 'operate-settings-form'
  async function reset() {
    if (await reload()) dispatch({ type: 'reset' })
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || pending || conflict) return
    dispatch({ type: 'submit' })
    const form = event.currentTarget
    if (Object.keys(errors).length) {
      requestAnimationFrame(() => {
        const field = form.querySelector<HTMLElement>('[aria-invalid="true"], [role="alert"]')
        if (field?.getAttribute('aria-invalid')) field.focus()
        else field?.scrollIntoView({ block: 'center' })
      })
      return
    }
    void props.save(current, draft.draft?.version ?? version).then(() => dispatch({ type: 'reset' }), error => {
      dispatch({ type: 'errors', errors: fieldErrors(error, props.prefix) })
    })
  }
  function enable() {
    dispatch({ type: 'edit', path: ['enabled'], next: true, base, version })
    document.getElementById(formId)?.scrollIntoView({ block: 'start' })
  }
  return <Stack gap={4}>
    {conflict && <ConflictBanner onReload={() => void reset()} />}
    {Boolean(props.loadError) && <LoadState error={props.loadError} retry={reset} />}
    {status === 403 && <Alert tone="warning">{t('behavior.forbidden')}</Alert>}
    {Boolean(props.error) && !conflict && status !== 403 && <Alert tone="danger">{t('operate.data', {
      value: errorInfo(props.error)?.message ?? t('common.actionFailed'),
    })}</Alert>}
    {props.saved && !draft.draft && <Alert tone="success">{t('operate.saved', { version })}</Alert>}
    {props.children?.(current, enable)}
    <Card><Stack>
      <h2>{props.title}</h2>
      <form data-schema-form id={formId} onSubmit={submit} noValidate aria-busy={pending}>
        <Stack>
          <SchemaFields key={draft.revision} schema={schema} value={current} readOnly={readOnly || pending}
            groupHeadings confirmRemove showEmptyRows options={path => props.options?.(path, current)}
            fieldOverride={field => props.fieldOverride?.(field, () => dispatch({ type: 'touch', path: field.path.join('.') }))}
            onChange={(path, next) => dispatch({ type: 'edit', path, next, version, base })}
            onBlur={path => dispatch({ type: 'touch', path })} onStructure={path => dispatch({ type: 'structure', path })}
            errors={shownErrors(draft, errors)} />
          {draft.submitted && Object.keys(errors).length > 0 && <Alert tone="danger">{t('operate.validate')}</Alert>}
          {!readOnly && <SaveBar dirty={Boolean(draft.draft)} pending={pending} readOnly={conflict}
            onDiscard={() => void reset()} onSave={() => (document.getElementById(formId) as HTMLFormElement | null)?.requestSubmit()} />}
        </Stack>
      </form>
      <p className="v2-muted">{t('operate.version', { version })}
        {props.updatedAt && <> · {t('operate.updated', { date: date(props.updatedAt) })}</>}
      </p>
      {props.aside?.(current)}
    </Stack></Card>
  </Stack>
}

export function EnableAction({ onClick }: { onClick: () => void }) {
  const t = useT()
  return <Button variant="primary" onClick={onClick}>{t('operate.enable')}</Button>
}
