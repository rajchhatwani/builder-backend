import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { AuthConfig, KeycloakConfig, SuiteJoinState } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, PageHeader, SettingsSection } from '../../patterns'
import { Alert, Button, Card, Checkbox, EmptyState, Grid, Row, Stack, Tabs } from '../../ui'
import { suiteIdentifier, suiteIssuer } from '../../validators'
import { authOptions, checksOptions, codeOf, fieldErrors, keycloakOptions, projectIssuesOptions, saveSuite, securityApi, suiteKeycloakBody,
  useSecureMutation } from './api/security'
import type { Migration, SavedSuite } from './api/security'
import { canEdit, Findings, groups, LoadFailure, pickField, readNullable, readText, SecureLink, SecureLoading, SecureRole,
  textField, useSecureSearch, WriteNotice } from './SecureForm'
import type { SecureProps } from './SecureForm'

const suiteRealm = (id: string) => 'suite-' + id.trim()
const joinStates: SuiteJoinState[] = ['none', 'planned', 'joined']

function MigrationWindow({ migration, onSettings }: { migration?: Migration | null; onSettings: () => void }) {
  const t = useT()
  const l = (key: string) => t('secure.suite.' + key)
  const date = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  return migration ? <SettingsSection title={l('migration')} description={l(migration.state + 'Help')}>
    <Grid>{[
      ['migrationState', l(migration.state)], ['legacyIssuer', migration.legacy_issuer],
      ['windowStart', migration.window_started_at && date(migration.window_started_at)],
      ['windowEnd', migration.dual_until && date(migration.dual_until)],
    ].filter(([, value]) => value).map(([label, value]) =>
      <Card key={label}><Stack gap={1}><strong>{l(label ?? '')}</strong><span>{value}</span></Stack></Card>)}</Grid>
  </SettingsSection> : <EmptyState title={l('migrationEmpty')} description={l('migrationEmptyDetail')}
    action={<Button onClick={onSettings}>{l('settings')}</Button>} />
}

function Membership({ id, editable, suite, keycloak, refresh }: {
  id: string; editable: boolean; suite: SavedSuite | null; keycloak: KeycloakConfig | null; refresh: () => void
}) {
  const t = useT()
  const l = (key: string) => t('secure.suite.' + key)
  const [enabled, setEnabled] = useState(Boolean(suite))
  const [suiteId, setSuiteId] = useState(suite?.suite_id ?? '')
  const [hub, setHub] = useState(suite?.hub_issuer ?? '')
  const [join, setJoin] = useState(suite?.join_state ?? 'none')
  const dirty = (suiteId.trim() !== (suite?.suite_id ?? '') || hub.trim() !== (suite?.hub_issuer ?? '') ||
    join !== (suite?.join_state ?? 'none'))
  const [revision, setRevision] = useState(0)
  const client = useQueryClient()
  const write = useSecureMutation(id, (next: SavedSuite | null) => saveSuite(id, suite, next))
  const sync = useSecureMutation(id, async (idForRealm: string) => {
    const latest = await client.fetchQuery({ ...keycloakOptions(id), staleTime: 0 })
    return securityApi.saveKeycloak(id, suiteKeycloakBody(latest, suiteRealm(idForRealm)))
  })
  const busy = write.isPending || sync.isPending
  const migrationOpen = Boolean(suite?.migration && suite.migration.state !== 'hub_only')
  const drift = Boolean(suite && (keycloak?.mode !== 'shared' || keycloak?.realm !== suiteRealm(suite.suite_id) || keycloak.source_project_id))
  const fields = groups([{ title: l('membership'), fields: [
    textField('suite_id', l('suiteId'), suiteId, {
      required: !suite?.migration, max: 56, checks: [suiteIdentifier], locked: Boolean(suite?.migration),
      controlled: true, change: setSuiteId, hint: l('suiteIdHelp'), placeholder: l('suitePlaceholder'),
    }),
    textField('hub_issuer', l('hubIssuer'), hub, {
      controlled: true, change: setHub,
      max: 512, checks: [suiteIssuer(suiteRealm(suiteId))], type: 'url', hint: l('issuerHelp'), placeholder: l('issuerPlaceholder'),
    }),
    pickField('join_state', l('joinState'), join, joinStates.map(value => ({ value, label: l(value) })), {
      locked: Boolean(suite?.migration), change: value => setJoin(value as SuiteJoinState),
      hint: l(suite?.migration ? 'migrationControlsJoin' : 'joinHelp'),
    }),
  ], extra: <Card><Stack gap={1}><strong>{l('realm')}</strong>
    <output data-testid="suite-realm" className="v2-mono">{suiteId.trim() ? suiteRealm(suiteId) : l('realmPlaceholder')}</output>
    <span>{l('realmHelp')}</span></Stack></Card> }])
  const revalidate = () => {
    void client.fetchQuery({ ...checksOptions(id), staleTime: 0 }).catch(() => undefined)
  }
  const syncSaved = async (realmId: string) => {
    try { await sync.mutateAsync(realmId) } catch { /* The persisted membership remains available for retry. */ }
    revalidate()
  }
  const submit = async (data: FormData) => {
    const next: SavedSuite = {
      suite_id: suite?.migration ? suite.suite_id : readText(data, 'suite_id'),
      hub_issuer: readNullable(data, 'hub_issuer'),
      join_state: suite?.migration ? suite.join_state : readText(data, 'join_state') as SuiteJoinState,
      ...(suite?.migration ? { migration: suite.migration } : {}),
    }
    try {
      await write.mutateAsync(next)
    } catch { return }
    await syncSaved(next.suite_id)
  }
  return <Stack>
    <WriteNotice error={write.error} message={l(codeOf(write.error) === 'suite_changed' ? 'suiteChanged' : 'saveError')}
      saved={(write.isSuccess && write.variables === null) ? l('removed') :
        sync.isSuccess && !drift ? l('saved') : undefined}
      reload={() => { write.reset(); refresh() }} />
    <WriteNotice error={sync.error} message={l('partial')} reload={() => { sync.reset(); refresh() }} />
    {(drift || sync.isError) && !busy && <Alert tone="warning" action={editable && <Button onClick={() => { if (suite) void syncSaved(suite.suite_id) }}>
      {l('retryKeycloak')}</Button>}>{l('drift')}</Alert>}
    {!suite && !enabled ? <EmptyState title={l('empty')} description={l('emptyDescription')}
      action={editable && <Checkbox label={l('part')} checked={false} onChange={() => { write.reset(); sync.reset(); setEnabled(true) }} />} />
      : <>
        <Checkbox label={l('part')} checked disabled={Boolean(suite) || busy || !editable}
          onChange={() => { setEnabled(false); setSuiteId(''); setHub(''); setJoin('none') }} />
        <Form key={revision} {...fields} submitLabel={t('common.save')} pending={busy} readOnly={!editable}
          submitProps={{ hidden: !editable, disabled: !dirty }} serverErrors={fieldErrors(write.error, {
            'suite.suite_id': 'suite_id', 'suite.hub_issuer': 'hub_issuer', 'suite.join_state': 'join_state',
          })} onSubmit={data => void submit(data)} actions={<Button disabled={busy} onClick={() => {
            setSuiteId(suite?.suite_id ?? ''); setHub(suite?.hub_issuer ?? ''); setJoin(suite?.join_state ?? 'none'); setEnabled(Boolean(suite)); setRevision(value => value + 1)
            write.reset(); sync.reset()
          }}>{t('common.discard')}</Button>} />
        {suite && editable && <Row>
          <ConfirmDestructive trigger={<Button variant="danger" disabled={busy || migrationOpen}>{l('remove')}</Button>}
            title={l('removeTitle')} description={t('secure.suite.removeDescription', { suite: suite.suite_id })} action={l('removeAction')}
            onConfirm={async () => {
              await write.mutateAsync(null)
              setEnabled(false); setSuiteId(''); setHub(''); setJoin('none'); sync.reset(); revalidate()
            }} />
          {migrationOpen && <span>{l('closeMigration')}</span>}
        </Row>}
      </>}
  </Stack>
}

export default function SuiteScreen(props: SecureProps) {
  const t = useT()
  const l = (key: string) => t('secure.suite.' + key)
  const { projectId: id } = props
  const { search, tab } = useSecureSearch()
  const auth = useQuery(authOptions(id))
  const keycloak = useQuery(keycloakOptions(id))
  const editable = canEdit(props)
  const checks = useQuery({ ...checksOptions(id), enabled: editable && Boolean(auth.data?.suite) })
  const savedStatus = useQuery({ ...projectIssuesOptions(id), enabled: !editable && Boolean(auth.data?.suite) })
  const issues = (checks.data?.issues ?? savedStatus.data?.issues ?? []).filter(item => item.path.startsWith('auth.suite') ||
    ['suite_realm_derived', 'suite_requires_shared'].includes(item.code))
  const [revision, setRevision] = useState(0)
  const reload = async () => {
    const result = await Promise.all([auth.refetch(), keycloak.refetch()])
    if (result.every(item => !item.isError)) setRevision(value => value + 1)
  }
  const config: AuthConfig | null | undefined = auth.data
  const suite = auth.data?.suite ?? null
  return <Stack gap={4}>
    <PageHeader title={l('title')} description={l('lead')} />
    <SecureRole {...props} />
    {auth.isPending || keycloak.isPending ? <SecureLoading label={l('loading')} />
      : auth.isError || keycloak.isError ? <LoadFailure error={auth.error ?? keycloak.error} message={l('loadError')} retry={() => void reload()} />
      : !config ? <EmptyState title={l('authEmpty')} description={l('authEmptyDetail')}
        action={<SecureLink id={id} section="auth" label={l('authLink')} />} />
      : <>
        {config.provider !== 'keycloak' && <Alert tone="warning" action={<SecureLink id={id} section="keycloak" label={l('keycloakLink')} />}>
          {l('needsKeycloak')}
        </Alert>}
        <Tabs label={l('title')} value={search.tab === 'migration' ? 'migration' : 'settings'} onChange={tab} items={[
          { id: 'settings', label: l('settings'), content: <Stack>
            <Membership key={revision} id={id} editable={editable} suite={suite} keycloak={keycloak.data ?? null} refresh={() => void reload()} />
            {!!issues.length && <SettingsSection title={l('issues')}><Findings issues={issues} /></SettingsSection>}
            {checks.isError && <LoadFailure error={checks.error} message={l('checksError')} retry={() => void checks.refetch()} />}
          </Stack> },
          { id: 'migration', label: l('migration'), content: <MigrationWindow migration={suite?.migration} onSettings={() => tab('settings')} /> },
        ]} />
      </>}
  </Stack>
}
