import { useMemo, useReducer, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { defaultFor } from '../../../forms/schemaLogic'
import type { Path } from '../../../forms/schemaLogic'
import { RouteTranslations, useT } from '../../i18n'
import english from '../../i18n/locales/connect-d/en.json'
import { ConfirmDestructive, ConflictBanner, PageHeader, ReadOnlyNote } from '../../patterns'
import { Alert, Button, Card, Dialog, EmptyState, Grid, Row, Skeleton, Stack } from '../../ui'
import { advancedPackIssues } from '../../validators/advancedPacks'
import { connectIssuesOptions, connectRolesOptions } from './api/blocks'
import { errorText, specOptions, statusOf } from './api/connect'
import type { ConnectProps } from './api/connect'
import { changePack, packFieldErrors, packsOptions, readPack, usePacksWrite } from './api/packs'
import type { PackBlock } from './api/packs'
import { AdvancedPackFields, packChoices, packFieldName } from './components/AdvancedPackFields'
import { AdvancedPackReference } from './components/AdvancedPackReference'
import { BlockLoad, BlockRole } from './components/BlockStatus'
import { advancedPackDefinitions, displaySchema, names, record, rows, strings } from './state/advancedPacks'
import type { AdvancedPackScreen } from './state/advancedPacks'
import { initialSchemaDraft, schemaDraftReducer, shownErrors } from './state/schemaDraft'
import './packs.css'
import './advanced-packs.css'

function PackSettings({ screen, ...props }: ConnectProps & { screen: AdvancedPackScreen }) {
  return <RouteTranslations english={english}><PackSettingsContent {...props} screen={screen} /></RouteTranslations>
}

function PackSettingsContent({ screen, ...props }: ConnectProps & { screen: AdvancedPackScreen }) {
  const { projectId, role, rolePending, roleError } = props
  const t = useT()
  const copy = (key: string) => t('connectD.screen.' + screen + '.' + key)
  const title = copy('title')
  const definition = advancedPackDefinitions[screen]
  const schema = useMemo(() => displaySchema(screen, t), [screen, t])
  const query = useQuery(packsOptions(projectId))
  const read = query.data
  const roles = useQuery({ ...connectRolesOptions(projectId), enabled: Boolean(read) })
  const spec = useQuery({ ...specOptions(projectId), enabled: Boolean(read) })
  const savedIssues = useQuery({ ...connectIssuesOptions(projectId), enabled: Boolean(read) })
  const mutation = usePacksWrite(projectId)
  const [state, dispatch] = useReducer(schemaDraftReducer, initialSchemaDraft)
  const [reloading, setReloading] = useState(false)
  const [review, setReview] = useState(false)
  const saveButton = useRef<HTMLButtonElement>(null)
  const header = <PageHeader title={title} description={copy('intro')} />

  if (!read) return <Stack gap={4}>
    {header}
    {query.error ? <BlockLoad error={query.error} errorKey={'connectD.screen.' + screen + '.loadError'}
      retry={() => void query.refetch()} /> : <Grid className="v2-pack-reference" gap={4}>
      <Stack><Card><Skeleton lines={7} /></Card><Card><Skeleton lines={5} /></Card></Stack>
      <Card><Skeleton lines={7} /></Card>
    </Grid>}
  </Stack>

  const saved = readPack(read.packs, definition.address)
  const draft = (state.draft?.value as PackBlock | undefined) ?? saved
  const readOnly = (role !== 'owner' && role !== 'editor') || Boolean(rolePending || roleError)
  const forbidden = statusOf(mutation.error) === 403
  const busy = mutation.isPending || reloading
  const version = state.draft?.version ?? read.version
  const conflict = statusOf(mutation.error) === 409 || (version !== read.version && !mutation.isPending)
  const gateway = screen === 'aigatewaysettings' ? draft : readPack(read.packs, ['ai', 'gateway'])
  const agents = screen === 'agentssettings' ? draft : readPack(read.packs, ['ai', 'agents'])
  const evals = readPack(read.packs, ['ai', 'evals'])
  const documents = readPack(read.packs, ['ai', 'documents'])
  const knowledge = readPack(read.packs, ['ai', 'knowledge'])
  const choices = packChoices({ screen, draft: draft ?? {}, roles: roles.data?.roles, spec: spec.data, gateway, agents, evals })
  const fieldLabel = (path: Path) => t('connectD.field.' + packFieldName(path))
  const validation = draft ? advancedPackIssues(screen, draft, choices, fieldLabel, t) : {}
  const errors = shownErrors(state, validation)
  const available = (section: string) => {
    const def = advancedPackDefinitions[section as AdvancedPackScreen]
    return { section, ready: def ? Boolean(readPack(read.packs, def.address)) :
      section === 'locationsettings' ? Boolean(readPack(read.packs, ['operations', 'location'])) : undefined }
  }
  const dependants = (Object.keys(advancedPackDefinitions) as AdvancedPackScreen[]).filter(section =>
    (advancedPackDefinitions[section].requiredPacks as readonly string[]).includes(screen) && available(section).ready)
  const retentionConflict = gateway?.zero_retention === true &&
    (screen === 'aigatewaysettings' ? Boolean(documents || agents) : screen === 'aidocssettings' || screen === 'agentssettings')
  const blockPath = 'packs.' + definition.address.join('.')
  const issues = savedIssues.data?.issues.filter(issue => issue.path === blockPath || issue.path.startsWith(blockPath + '.') ||
    definition.address[0] === 'ai' && issue.path === 'packs.ai') ?? []

  const reviewNotes: string[] = []
  if (saved && draft && state.draft) {
    const oldRoles = saved.roles ? record(saved.roles) : saved
    const nextRoles = draft.roles ? record(draft.roles) : draft
    for (const [field, value] of Object.entries(nextRoles)) {
      if (!field.endsWith('_roles')) continue
      const before = strings(oldRoles[field])
      const after = strings(value)
      const emptyGrantsAccess = field !== 'read_roles' || !['aidocssettings', 'agentssettings'].includes(screen)
      if ((before.length || !emptyGrantsAccess) && ((!after.length && emptyGrantsAccess) || after.some(role => !before.includes(role)))) {
        reviewNotes.push(t('connectD.accessChange', { field: t('connectD.field.' + field) }))
      }
    }
    if (draft.allow_self_review === true && saved.allow_self_review === false) reviewNotes.push(t('connectD.help.allow_self_review'))
    if (draft.allow_self_approval === true && saved.allow_self_approval === false) reviewNotes.push(t('connectD.help.allow_self_approval'))
    if (screen === 'agentssettings' && ['agents', 'actions'].some(field => rows(draft[field]).some(row =>
      (row.autonomy === 'auto' || row.max_autonomy === 'auto') && !rows(saved[field]).some(old =>
        old.name === row.name && old.autonomy === row.autonomy && old.max_autonomy === row.max_autonomy)))) {
      reviewNotes.push(t('connectD.autoChange'))
    }
    if (screen === 'aigatewaysettings' && names(saved.stages).some(name =>
      !names(draft.stages).includes(name) && [documents?.stage, knowledge?.stage, ...rows(agents?.agents).map(agent => agent.stage)].includes(name))) {
      reviewNotes.push(t('connectD.stageChange'))
    }
    if (screen === 'evalssettings' && rows(agents?.agents).some(agent =>
      typeof agent.require_eval === 'string' && names(saved.suites).includes(agent.require_eval) && !names(draft.suites).includes(agent.require_eval))) {
      reviewNotes.push(t('connectD.suiteChange'))
    }
  }

  async function write(value: PackBlock | null) {
    if (!read || readOnly || busy || conflict || forbidden) return
    try {
      await mutation.mutateAsync({ packs: changePack(read.packs, definition.address, value), version })
      dispatch({ type: 'reset' })
    } catch (error) {
      dispatch({ type: 'errors', errors: packFieldErrors(error, definition.address) })
      throw error
    }
  }

  async function reload() {
    setReloading(true)
    try {
      const result = await query.refetch()
      if (!result.isSuccess) return
      mutation.reset()
      dispatch({ type: 'reset' })
    } finally { setReloading(false) }
  }

  function focusErrors(form: HTMLFormElement, paths: string[] = []) {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const first = form.querySelector<HTMLElement>('[aria-invalid="true"]')
      const group = Array.from(form.querySelectorAll<HTMLElement>('[data-field-path]'))
        .find(element => paths.includes(element.dataset.fieldPath ?? ''))
      ;(first ?? group?.querySelector<HTMLElement>('input,textarea,[role="combobox"],button') ??
        form.querySelector<HTMLElement>('[data-row-action="add"]'))?.focus()
    }))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || busy || conflict || forbidden || !state.draft || !draft) return
    mutation.reset()
    dispatch({ type: 'submit' })
    const form = event.currentTarget
    if (Object.keys(validation).length) {
      focusErrors(form, Object.keys(validation))
      return
    }
    if (reviewNotes.length) {
      setReview(true)
      return
    }
    void write(draft).catch(error => {
      if (statusOf(error) === 422) focusErrors(form, Object.keys(packFieldErrors(error, definition.address)))
    })
  }

  const removeImpact = (path: Path, value: unknown) => {
    const name = record(value).name
    if (path[0] === 'suites' && path.length === 1 && rows(agents?.agents).some(agent => name === agent.require_eval)) {
      return t('connectD.suiteChange')
    }
    if (path[0] === 'stages' && [documents?.stage, knowledge?.stage, ...rows(agents?.agents).map(agent => agent.stage)].includes(name)) {
      return t('connectD.stageChange')
    }
  }

  return <Stack gap={4} className="v2-advanced-pack">
    {header}
    <BlockRole {...props} />
    {(!role && !rolePending && !roleError || forbidden) && <ReadOnlyNote>{t('behavior.forbidden')}</ReadOnlyNote>}
    {query.isRefetchError && <BlockLoad error={query.error} errorKey={'connectD.screen.' + screen + '.loadError'} retry={() => void reload()} />}
    {conflict && <div data-testid="conflict"><ConflictBanner
      action={<Button disabled={busy} onClick={() => void reload()}>{t('common.reload')}</Button>}>{t('connectD.conflict')}</ConflictBanner></div>}
    {mutation.isError && !forbidden && !conflict && <Alert tone="danger">
      {t('connectA2.writeError', { message: errorText(mutation.error) ?? t('common.actionFailed') })}
    </Alert>}
    {Object.entries(errors).filter(([path]) => !draft || path === '').flatMap(([, messages]) => messages).map(message =>
      <Alert key={message} tone="danger">{t('common.serverText', { text: message })}</Alert>)}
    {(roles.isError || spec.isError || savedIssues.isError) && <Alert tone="warning" action={<Button onClick={() => {
      if (roles.isError) void roles.refetch()
      if (spec.isError) void spec.refetch()
      if (savedIssues.isError) void savedIssues.refetch()
    }}>{t('common.retry')}</Button>}>{t('connectD.dependenciesError')}</Alert>}
    {issues.length > 0 && <Card><Stack><h2>{t('connectA2.issues')}</h2>
      <ul>{issues.map(({ path, message, code }, index) =>
        <li key={path + code + index}>{t('connectA2.issue', { path, message })}</li>)}</ul>
    </Stack></Card>}
    <Grid className="v2-pack-reference" gap={4}>
      <Stack>
        {draft ? <>
          <form noValidate aria-busy={busy} onSubmit={submit}>
            <Stack gap={4}>
              <AdvancedPackFields screen={screen} schema={schema} draft={draft} errors={errors} roles={roles.data?.roles}
                readOnly={readOnly || busy || forbidden} revision={state.revision} choices={choices} removeImpact={removeImpact}
                onChange={(path, next) => dispatch({ type: 'edit', path, next, base: saved, version: read.version })}
                onBlur={path => dispatch({ type: 'touch', path })} onStructure={path => dispatch({ type: 'structure', path })} />
              <Card><Row>
                {!readOnly && <>
                  <Button disabled={busy || !state.draft} onClick={() => void reload()}>{t('common.discard')}</Button>
                  <Button ref={saveButton} type="submit" variant="primary" disabled={busy || conflict || forbidden || !state.draft}>
                    {t(mutation.isPending ? 'connectA2.saving' : 'common.save')}
                  </Button>
                </>}
                <span role="status" data-testid="save-note">{mutation.isSuccess && !state.draft ? t('connectA2.saved', { version: read.version })
                  : state.draft ? t('connectD.unsaved') : ''}</span>
              </Row></Card>
            </Stack>
          </form>
          {!readOnly && <Card><Stack>
            <h2>{t('connectD.switchOffHeading')}</h2>
            <Row data-testid="switch-off"><ConfirmDestructive
              trigger={<Button variant="danger" disabled={busy || conflict || forbidden}>{t('connectD.switchOff', { name: copy('name') })}</Button>}
              title={t('connectD.switchOff', { name: copy('name') })} description={t('connectD.switchOffHelp')}
              action={t('connectD.switchOffAction')} closeLabel={t('connectD.keepOn')}
              disabled={busy || conflict || forbidden} onConfirm={() => write(null)}>
              {dependants.map(section => <p key={section}>{t('connectD.dependsOn', { title: t('nav.' + section) })}</p>)}
              {screen === 'evalssettings' && rows(agents?.agents).some(agent => agent.require_eval != null) &&
                <p>{t('connectD.suiteChange')}</p>}
              {state.draft && <p>{t('connectD.discardDraft')}</p>}
            </ConfirmDestructive></Row>
          </Stack></Card>}
        </> : <Stack data-testid="block-off">
          <EmptyState title={t('connectD.offTitle', { title })} description={t('connectD.offHelp')} action={!readOnly &&
            <Button variant="primary" disabled={busy || conflict || forbidden}
              onClick={() => void write(defaultFor(schema, schema) as PackBlock).catch(() => undefined)}>
              {mutation.isPending ? t('connectD.switchingOn') : t('connectD.switchOn', { name: copy('name') })}
            </Button>} />
          {mutation.isSuccess && <Alert tone="success"><span data-testid="save-note">{t('connectA2.saved', { version: read.version })}</span></Alert>}
        </Stack>}
      </Stack>
      <AdvancedPackReference projectId={projectId} screen={screen} draft={draft} roles={roles.data?.roles} spec={spec.data}
        prerequisites={definition.requiredPacks.map(available)} related={definition.related.map(available)} gateway={gateway} agents={agents}
        retentionConflict={retentionConflict} version={read.version} row={read.row_version} updated={read.updated_at} />
    </Grid>
    <Dialog title={t('connectD.reviewChange')} description={t('connectD.reviewHelp')} open={review} onOpenChange={setReview}
      closeLabel={t('common.cancel')} returnFocus={saveButton} actions={<Button variant="primary"
        disabled={busy || conflict || forbidden || readOnly} onClick={() => {
          if (!draft) return
          setReview(false)
          void write(draft).catch(() => undefined)
        }}>{t('common.save')}</Button>}>
      <Stack>{reviewNotes.map(text => <p key={text}>{t('common.serverText', { text })}</p>)}</Stack>
    </Dialog>
  </Stack>
}

export const MatchingSettings = (props: ConnectProps) => <PackSettings {...props} screen="matchingsettings" />
export const PredictionSettings = (props: ConnectProps) => <PackSettings {...props} screen="predictionsettings" />
export const GatewaySettings = (props: ConnectProps) => <PackSettings {...props} screen="aigatewaysettings" />
export const DocumentsSettings = (props: ConnectProps) => <PackSettings {...props} screen="aidocssettings" />
export const KnowledgeSettings = (props: ConnectProps) => <PackSettings {...props} screen="knowledgesettings" />
export const AgentsSettings = (props: ConnectProps) => <PackSettings {...props} screen="agentssettings" />
export const EvalsSettings = (props: ConnectProps) => <PackSettings {...props} screen="evalssettings" />
