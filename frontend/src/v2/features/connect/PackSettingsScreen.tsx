import { useReducer, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { RouteTranslations, useT } from '../../i18n'
import english from '../../i18n/locales/connect-c/en.json'
import { ConfirmDestructive, ConflictBanner, PageHeader, ReadOnlyNote } from '../../patterns'
import { Alert, Button, Card, Dialog, EmptyState, Grid, Row, Skeleton, Stack } from '../../ui'
import { packDraftIssues, reconciliationCeiling } from '../../validators'
import { connectRolesOptions } from './api/blocks'
import { errorText, specOptions, statusOf } from './api/connect'
import type { ConnectProps } from './api/connect'
import { changePack, packFieldErrors, packsOptions, readPack, usePacksWrite } from './api/packs'
import type { PackBlock } from './api/packs'
import { BlockLoad, BlockRole, Issues } from './components/BlockStatus'
import { PackFields } from './components/PackFields'
import { PackReference } from './components/PackReference'
import { packDefinitions } from './state/packs'
import type { PackId } from './state/packs'
import { initialSchemaDraft, schemaDraftReducer, shownErrors } from './state/schemaDraft'
import './packs.css'

const moneyScreens: PackId[] = ['currencysettings', 'ledgersettings', 'reconsettings', 'invoicingsettings']
const operationsScreens: PackId[] = ['geosettings', 'locationsettings']

function PackSettings({ screen, ...props }: ConnectProps & { screen: PackId }) {
  return <RouteTranslations english={english}><PackSettingsContent {...props} screen={screen} /></RouteTranslations>
}

function PackSettingsContent({ screen, ...props }: ConnectProps & { screen: PackId }) {
  const { projectId, role, rolePending, roleError } = props
  const t = useT()
  const def = packDefinitions[screen]
  const title = t('nav.' + screen)
  const packCopy = (key: string) => t('connectC.screen.' + screen + '.' + key)
  const label = (key: string) => t('connectC.' + key, { title, name: packCopy('name') })
  const query = useQuery(packsOptions(projectId))
  const mutation = usePacksWrite(projectId)
  const roles = useQuery({ ...connectRolesOptions(projectId), enabled: Boolean(def.roles) && Boolean(query.data) })
  const spec = useQuery({ ...specOptions(projectId), enabled: Boolean(def.roles) && Boolean(query.data) })
  const [state, dispatch] = useReducer(schemaDraftReducer, initialSchemaDraft)
  const [review, setReview] = useState(false)
  const [reloading, setReloading] = useState(false)
  const saveButton = useRef<HTMLButtonElement>(null)
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const header = <PageHeader title={title} description={packCopy('intro')} />
  const read = query.data

  if (!read) return <Stack gap={4}>
    {header}
    {query.error ? <BlockLoad error={query.error} errorKey={'connectC.screen.' + screen + '.loadError'}
      retry={() => void query.refetch()} /> : <Grid className="v2-pack-reference" gap={4}>
      <Stack>
        <Card><Skeleton lines={7} /></Card>
        <Card><Skeleton lines={5} /></Card>
      </Stack>
      <Card><Skeleton lines={7} /></Card>
    </Grid>}
  </Stack>

  const saved = readPack(read.packs, def.address)
  const draft = (state.draft?.value as PackBlock | undefined) ?? saved
  const kind = def.address[1] ?? def.address[0]
  const readOnly = (role !== 'owner' && role !== 'editor') || Boolean(roleError || rolePending)
  const revision = state.draft?.version ?? read.version
  const conflict = statusOf(mutation.error) === 409 || revision !== read.version && !mutation.isPending
  const forbidden = statusOf(mutation.error) === 403
  const busy = mutation.isPending || reloading
  const ceiling = reconciliationCeiling(readPack(read.packs, ['money', 'currency'])?.currencies)
  const issues = draft ? packDraftIssues(kind, draft, ceiling, t) : {}
  const errors = shownErrors(state, issues)

  const warnings = saved && draft && state.draft ? [
    ...def.roles?.filter(field => Array.isArray(saved[field]) && saved[field].length &&
      Array.isArray(draft[field]) && !draft[field].length).map(field => field === 'manage_roles'
      ? t('connectC.managerChange') : t('connectC.roleChange', { field: t('connectC.field.' + field) })) ?? [],
    ...(kind === 'geo' && saved.grid_cell_micro !== draft.grid_cell_micro ? [t('connectC.gridChange')] : []),
    ...(kind === 'location' && Number(draft.history_cap) < Number(saved.history_cap) ? [t('connectC.retentionChange')] : []),
  ] : []
  const impacts = (def.dependants ?? []).filter(item => readPack(read.packs, item.address)).map(item => t('connectC.' + item.key))
  if (kind === 'invoicing' && saved?.payouts) impacts.push(t('connectC.payoutsRemoved'))
  if (kind === 'booking' && Array.isArray(saved?.kinds)) impacts.push(t('connectC.bookingRemoved', { count: saved.kinds.length }))
  if (state.draft) impacts.push(t('connectC.draftRemoved'))

  async function write(value: PackBlock | null) {
    if (!read || readOnly || busy || conflict) return
    try {
      await mutation.mutateAsync({ packs: changePack(read.packs, def.address, value), version: revision })
      dispatch({ type: 'reset' })
    } catch (error) {
      dispatch({ type: 'errors', errors: packFieldErrors(error, def.address) })
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

  async function focusErrors(form: HTMLFormElement, paths: string[]) {
    const first = paths[0]
    const kindRow = first && /^kinds\.(\d+)\./.exec(first)
    if (kindRow) await navigate({ search: previous => ({ ...previous, bookingKind: Number(kindRow[1]) }), replace: true })
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const invalid = form.querySelector<HTMLElement>('[aria-invalid="true"], [data-field-path="' + first + '"] summary')
      const collapsed = invalid?.closest('details')
      if (collapsed) collapsed.open = true
      ;(invalid ?? form.querySelector<HTMLElement>('[data-row-action="add"]'))?.focus()
    }))
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || busy || conflict || !state.draft || !draft) return
    mutation.reset()
    dispatch({ type: 'submit' })
    const paths = Object.keys(issues)
    if (paths.length || event.currentTarget.querySelector('[data-json-invalid]')) {
      void focusErrors(event.currentTarget, paths)
      return
    }
    if (warnings.length) setReview(true)
    else {
      const form = event.currentTarget
      void write(draft).catch(error => {
        if (statusOf(error) === 422) {
          const paths = Object.keys(packFieldErrors(error, def.address)).filter(path => /^[\w.]+$/.test(path))
          void focusErrors(form, paths)
        }
      })
    }
  }

  const packAvailability = (section: PackId) => ({ section, ready: Boolean(readPack(read.packs, packDefinitions[section].address)) })
  const requirements = [
    ...(def.prerequisites ?? []).map(packAvailability),
    ...(def.roles ? [
      { section: 'auth', ready: spec.data ? Boolean(spec.data.auth?.enabled) : undefined },
      { section: 'access', ready: spec.data ? !spec.data.authorization || spec.data.authorization.model === 'rbac' : undefined },
    ] : []),
  ]
  const related = (def.address[0] === 'money' ? moneyScreens : def.address[0] === 'operations' ? operationsScreens : [])
    .filter(section => section !== screen).map(packAvailability)

  return <Stack gap={4}>
    {header}
    <BlockRole {...props} />
    {!role && !rolePending && !roleError && <ReadOnlyNote>{t('behavior.forbidden')}</ReadOnlyNote>}
    {conflict && <div data-testid="conflict"><ConflictBanner action={<Button disabled={busy} onClick={() => void reload()}>{t('common.reload')}</Button>}>
      {t('connectC.conflict')}
    </ConflictBanner></div>}
    {query.isRefetchError && <BlockLoad error={query.error} errorKey={'connectC.screen.' + screen + '.loadError'} retry={() => void reload()} />}
    {forbidden && <ReadOnlyNote>{t('behavior.forbidden')}</ReadOnlyNote>}
    {mutation.isError && !conflict && !forbidden && <Alert tone="danger">
      {t('connectA2.writeError', { message: errorText(mutation.error) ?? t('common.actionFailed') })}
    </Alert>}
    {errors['']?.length > 0 && <Alert tone="danger">{t('common.serverText', { text: errors[''].join(' ') })}</Alert>}
    {(roles.isError || spec.isError) && <Alert tone="warning" action={<Button onClick={() => {
      if (roles.isError) void roles.refetch()
      if (spec.isError) void spec.refetch()
    }}>{t('common.retry')}</Button>}>{t('connectA2.dependenciesError')}</Alert>}
    <Issues id={projectId} block={'packs.' + def.address.join('.')} />
    <Grid className="v2-pack-reference" gap={4}>
      <Stack>
        {draft ? <>
          <form noValidate data-schema-form aria-busy={busy} onSubmit={submit}>
            <Stack gap={4}>
              <PackFields definition={def} value={draft} errors={errors} readOnly={readOnly || busy || forbidden}
                roles={roles.data?.roles ?? []} ceiling={ceiling} revision={state.revision}
                onChange={(path, next) => dispatch({ type: 'edit', path, next, base: saved, version: read.version })}
                onBlur={path => dispatch({ type: 'touch', path })} onStructure={path => dispatch({ type: 'structure', path })} />
              <Card><Row>
                {!readOnly && <>
                  <Button disabled={busy || !state.draft} onClick={() => void reload()}>{t('common.discard')}</Button>
                  <Button ref={saveButton} type="submit" variant="primary" disabled={busy || conflict || forbidden || !state.draft}>
                    {t(busy && mutation.isPending ? 'connectA2.saving' : 'common.save')}
                  </Button>
                </>}
                <span role="status" data-testid="save-note">{mutation.isSuccess && !state.draft ? t('connectA2.saved', { version: read.version })
                  : state.draft ? t('connectC.unsaved') : ''}</span>
              </Row></Card>
            </Stack>
          </form>
          {!readOnly && <Card><Stack>
            <h2>{t('connectC.switchOffHeading')}</h2>
            <Row data-testid="switch-off"><ConfirmDestructive
              trigger={<Button variant="danger" disabled={busy || conflict || forbidden}>{label('switchOff')}</Button>}
              title={label('switchOff')} description={t('connectC.switchOffHelp')} action={t('connectC.switchOffAction')}
              closeLabel={t('connectC.keepOn')} disabled={busy || conflict || forbidden} onConfirm={() => write(null)}>
              {impacts.map(text => <p key={text}>{t('common.serverText', { text })}</p>)}
            </ConfirmDestructive></Row>
          </Stack></Card>}
        </> : <Stack data-testid="block-off">
          <EmptyState title={label('offTitle')} description={t('connectC.offHelp')} action={!readOnly &&
            <Button variant="primary" disabled={busy || conflict || forbidden} onClick={() => void write(def.defaults).catch(() => undefined)}>
              {busy && mutation.isPending ? t('connectC.switchingOn') : label('switchOn')}
            </Button>} />
          {mutation.isSuccess && <Alert tone="success"><span data-testid="save-note">{t('connectA2.saved', { version: read.version })}</span></Alert>}
          {kind === 'booking' && <p>{t('connectC.bookingOnHint')}</p>}
        </Stack>}
      </Stack>
      <PackReference projectId={projectId} screen={screen} draft={draft} roles={roles.data?.roles ?? []} prerequisites={requirements}
        related={related} ceiling={ceiling} version={read.version} row={read.row_version} updated={read.updated_at}
        geo={Boolean(readPack(read.packs, ['operations', 'geo']))} />
    </Grid>
    <Dialog title={t('connectC.reviewChange')} description={t('connectC.reviewHelp')} open={review} onOpenChange={setReview}
      closeLabel={t('common.cancel')} returnFocus={saveButton}
      actions={<Button variant="primary" disabled={busy || conflict || forbidden || readOnly} onClick={() => {
        if (!draft) return
        setReview(false)
        void write(draft).catch(() => undefined)
      }}>{t('common.save')}</Button>}>
      <Stack>{warnings.map(text => <p key={text}>{t('common.serverText', { text })}</p>)}</Stack>
    </Dialog>
  </Stack>
}

export const LedgerSettings = (props: ConnectProps) => <PackSettings {...props} screen="ledgersettings" />
export const CurrencySettings = (props: ConnectProps) => <PackSettings {...props} screen="currencysettings" />
export const ReconSettings = (props: ConnectProps) => <PackSettings {...props} screen="reconsettings" />
export const InvoicingSettings = (props: ConnectProps) => <PackSettings {...props} screen="invoicingsettings" />
export const BookingSettings = (props: ConnectProps) => <PackSettings {...props} screen="bookingsettings" />
export const GeoSettings = (props: ConnectProps) => <PackSettings {...props} screen="geosettings" />
export const LocationSettings = (props: ConnectProps) => <PackSettings {...props} screen="locationsettings" />
