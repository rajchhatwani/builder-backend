import { useReducer } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { validateValue } from '../../../../forms/schemaLogic'
import type { Path } from '../../../../forms/schemaLogic'
import type { JsonSchema } from '../../../../forms/types'
import { useLanguage } from '../../../i18n'
import { ConfirmDestructive, ConflictBanner } from '../../../patterns'
import type { SchemaFieldOverride } from '../../../patterns/SchemaFields'
import { SchemaFields } from '../../../patterns/SchemaFields'
import { Alert, Button, Card, Row, Stack } from '../../../ui'
import type { SelectOption } from '../../../ui'
import { blockFieldErrors, blockOptions, useBlockWrite } from '../api/blocks'
import type { BlockName, Blocks } from '../api/blocks'
import { errorText, statusOf } from '../api/connect'
import { blockDraftIssues } from '../../../validators'
import { initialSchemaDraft, schemaDraftReducer, shownErrors } from '../state/schemaDraft'
import { BlockLoad, Issues } from './BlockStatus'

type Props<K extends BlockName> = {
  projectId: string; name: K; schema: JsonSchema; defaults: Blocks[K]; readOnly: boolean; title: string; errorKey: string
  remove?: boolean; prepare?: (value: Blocks[K]) => Blocks[K]
  validate?: (value: Blocks[K]) => Record<string, string[]>
  empty?: ReactNode; children?: (current: Blocks[K]) => ReactNode
  options?: (path: Path, current: Blocks[K]) => SelectOption[] | undefined
  fieldOverride?: (props: SchemaFieldOverride, current: Blocks[K]) => ReactNode
  selectedRow?: (path: Path) => { index?: number; select: (index?: number) => void } | undefined
}

export function BlockSettings<K extends BlockName>({ projectId, name, schema, defaults, readOnly, title, errorKey, empty, children, options, selectedRow, fieldOverride, remove, prepare, validate }: Props<K>) {
  const { t, language } = useLanguage()
  const query = useQuery(blockOptions(projectId, name))
  const mutation = useBlockWrite(projectId, name)
  const [state, dispatch] = useReducer(schemaDraftReducer, initialSchemaDraft)
  const read = query.data
  if (!read) return <BlockLoad error={query.error} retry={() => void query.refetch()} errorKey={errorKey} />
  const base = read.block && prepare ? prepare(read.block) : read.block ?? defaults
  const current = (state.draft?.value ?? base) as Blocks[K]
  const disabled = readOnly || mutation.isPending
  const version = state.draft?.version ?? read.version
  const conflict = statusOf(mutation.error) === 409
  const issues = {
    ...validateValue(schema, schema, current),
    ...(name === 'notifications' || name === 'webhooks' ? blockDraftIssues(name, current as Blocks['notifications' | 'webhooks'], t) : validate?.(current)),
  }
  async function save(block: Blocks[K] | null) {
    try {
      await mutation.mutateAsync({ block, version })
      dispatch({ type: 'reset' })
    } catch (error) {
      dispatch({ type: 'errors', errors: blockFieldErrors(error, name) })
      throw error
    }
  }
  async function reload() {
    const result = await query.refetch()
    if (!result.isSuccess) return
    mutation.reset()
    dispatch({ type: 'reset' })
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (disabled || conflict) return
    dispatch({ type: 'submit' })
    const form = event.currentTarget
    if (Object.keys(issues).length || form.querySelector('[data-json-invalid]')) {
      const first = Object.keys(issues)[0]?.split('.').map(part => /^\d+$/.test(part) ? Number(part) : part)
      if (first && typeof first[1] === 'number') selectedRow?.([first[0]])?.select(first[1])
      const focusInvalid = () => form.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
      requestAnimationFrame(() => requestAnimationFrame(focusInvalid))
      return
    }
    void save(current).catch(() => undefined)
  }
  return <Stack>
    {conflict && <ConflictBanner onReload={() => void reload()} />}
    {query.isRefetchError && <BlockLoad error={query.error} retry={() => void reload()} errorKey={errorKey} />}
    {statusOf(mutation.error) === 403 && <Alert tone="warning">{t('behavior.forbidden')}</Alert>}
    {mutation.isError && !conflict && statusOf(mutation.error) !== 403 && <Alert tone="danger">{t('connectA2.writeError', {
      message: errorText(mutation.error) ?? t('common.actionFailed'),
    })}</Alert>}
    {mutation.isSuccess && <Alert tone="success">{t('connectA2.saved', { version: read.version })}</Alert>}
    <Issues id={projectId} block={name} />
    {read.block == null && empty}
    {children?.(current)}
    <Card><Stack>
      <h2>{title}</h2>
      <form noValidate onSubmit={submit} aria-busy={mutation.isPending}>
        <Stack>
          <SchemaFields key={state.revision} schema={schema} value={current} readOnly={disabled}
            options={path => options?.(path, current)} fieldOverride={props => fieldOverride?.(props, current)}
            selectedRow={selectedRow} confirmRemove
            onChange={(path, next) => dispatch({ type: 'edit', path, next, base, version: read.version })}
            onBlur={path => dispatch({ type: 'touch', path })} onStructure={path => dispatch({ type: 'structure', path })}
            errors={shownErrors(state, issues)} />
          {!readOnly && <Row>
            <Button type="submit" variant="primary" disabled={disabled || conflict || Boolean(read.block && !state.draft)}
              >{t(mutation.isPending ? 'connectA2.saving' : 'common.save')}</Button>
            <Button disabled={disabled || !state.draft} onClick={() => void reload()}>{t('common.discard')}</Button>
          </Row>}
        </Stack>
      </form>
      <p className="v2-muted">{t('connectA2.version', { version: read.version, row: read.row_version ?? 0 })}</p>
      {read.updated_at && <p className="v2-muted">{t('connectA2.updated', { date: new Intl.DateTimeFormat(language, {
        dateStyle: 'medium', timeStyle: 'short',
      }).format(new Date(read.updated_at)) })}</p>}
    </Stack></Card>
    {(name === 'notifications' || remove) && read.block && !readOnly && <Row><ConfirmDestructive
      trigger={<Button variant="danger" disabled={disabled || conflict}>{t(remove ? 'connectB.remove' : 'connectA2.types.remove')}</Button>}
      title={t(remove ? 'connectB.remove' : 'connectA2.types.removeTitle')} description={t(remove ? 'connectB.removeHelp' : 'connectA2.types.removeHelp')}
      disabled={disabled || conflict} action={t(remove ? 'connectB.remove' : 'connectA2.types.removeAction')} onConfirm={() => save(null)} /></Row>}
  </Stack>
}
