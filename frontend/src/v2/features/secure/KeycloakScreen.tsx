import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useReducer, useRef, useState } from 'react'
import type { Dispatch } from 'react'
import type { IdpType, IdentityProvider, KeycloakConfig, KeycloakWrite, Project } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, PageHeader, SettingsSection } from '../../patterns'
import { Alert, Button, Card, EmptyState, Field, Grid, Input, Progress, Radio, Row, Skeleton, Stack } from '../../ui'
import { hookUuid, keycloakAlias, keycloakClient, keycloakEndpoint, keycloakProviderClient, keycloakRealm,
  keycloakRedirects, orderedNumber, orgSsoDomain, secureAddress, signInLine } from '../../validators'
import { discoverOidc } from './api/discovery'
import { authOptions, codeOf, fieldErrors, impactOptions, keycloakDefaults, keycloakOptions, projectInfoOptions, projectIssuesOptions,
  securityApi, sourceOptions, useSecureMutation } from './api/security'
import type { SavedSuite } from './api/security'
import { canEdit, duplicateValue, Findings, groups, LoadFailure, numberField, pickField, readLines, readNullable, readNumber,
  readText, SecureLink, SecureLoading, SecureRole, textField, WriteNotice } from './SecureForm'
import type { SecureProps } from './SecureForm'
import { oidcFields, providersReducer, providerState } from './state/providers'
import type { ProviderAction, ProviderRow } from './state/providers'

const commonEnvironment = ['KEYCLOAK_PUBLIC_URL', 'API_PUBLIC_URL', 'SMTP_USERNAME', 'SMTP_PASSWORD']
const ownEnvironment = ['KEYCLOAK_DB_PASSWORD', 'KC_BOOTSTRAP_ADMIN_USERNAME', 'KC_BOOTSTRAP_ADMIN_PASSWORD']
const sharedEnvironment = ['KEYCLOAK_ADMIN_USERNAME', 'KEYCLOAK_ADMIN_PASSWORD']
const providerTypes: IdpType[] = ['google', 'microsoft', 'github', 'oidc']

function Discovery({ disabled, onFill }: {
  disabled: boolean; onFill: (fields: Partial<IdentityProvider>) => void
}) {
  const t = useT()
  const l = (key: string) => t('secure.keycloak.' + key)
  const [address, setAddress] = useState('')
  const [state, setState] = useState<'idle' | 'loading' | 'invalid' | 'failed' | 'filled'>('idle')
  const controller = useRef<AbortController>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const fill = async () => {
    if (!secureAddress(address.trim()) || address.includes('?')) { setState('invalid'); return }
    const signal = new AbortController()
    controller.current?.abort()
    controller.current = signal
    setState('loading')
    try {
      const values = await discoverOidc(address, signal.signal)
      if (!signal.signal.aborted) { onFill(values); setState('filled') }
    } catch {
      if (!signal.signal.aborted) setState('failed')
    }
  }
  return <Stack>
    <Field label={l('discoveryAddress')} hint={l('discoveryHelp')} error={state === 'invalid' ? l('discoveryInvalid') : undefined}>
      {attributes => <Input {...attributes} type="url" value={address} maxLength={2000} disabled={disabled || state === 'loading'}
        onChange={event => { setAddress(event.target.value); setState('idle') }} />}
    </Field>
    <Row><Button disabled={disabled || state === 'loading'} onClick={() => void fill()}>{l('discover')}</Button></Row>
    {state === 'loading' && <Skeleton label={l('discoveryLoading')} lines={1} />}
    {state === 'failed' && <Alert tone="danger">{l('discoveryError')}</Alert>}
    {state === 'filled' && <Alert tone="success">{l('discoverySaved')}</Alert>}
  </Stack>
}

function SwitchProvider({ id, action, close, reload }: { id: string; action: 'enable' | 'disable'; close: () => void; reload: () => void }) {
  const t = useT()
  const l = (key: string) => t('secure.keycloak.' + key)
  const impact = useQuery({ ...impactOptions(id, action), refetchOnMount: 'always' })
  const write = useSecureMutation(id, () => securityApi.switchKeycloak(id, action))
  return <ConfirmDestructive open onOpenChange={open => { if (!open && !write.isPending) close() }}
    title={l(action === 'enable' ? 'enableTitle' : 'disableTitle')} description={l('impactDescription')}
    action={l(action === 'enable' ? 'enableAction' : 'disableAction')}
    disabled={impact.isFetching || impact.isError || !impact.data?.can_proceed} pending={write.isPending}
    onConfirm={async () => { await write.mutateAsync(); reload() }}>
    <Stack>
      {impact.isPending && <Skeleton label={l('impactLoading')} />}
      {impact.isError && <LoadFailure error={impact.error} message={l('impactError')} retry={() => void impact.refetch()} />}
      {impact.data && <>
        {impact.data.blockers.map((message, index) => <Alert key={index} tone="danger">{t('secure.serverText', { message })}</Alert>)}
        {impact.data.warnings.map((message, index) => <Alert key={index} tone="warning">{t('secure.serverText', { message })}</Alert>)}
        {!!impact.data.dependents.length && <Stack gap={1}><strong>{l('dependents')}</strong>
          {impact.data.dependents.map(project => <span key={project.id}>{project.name}</span>)}</Stack>}
      </>}
      <WriteNotice error={write.error} message={l('switchError')} reload={() => { write.reset(); void impact.refetch() }} />
    </Stack>
  </ConfirmDestructive>
}

function providerBody(row: ProviderRow, data: FormData): IdentityProvider {
  const get = (name: string) => readNullable(data, 'provider.' + row.key + '.' + name)
  const type = row.value.type
  return {
    type, alias: get('alias') ?? '', client_id: get('client_id') ?? '', display_name: get('display_name'),
    tenant_id: type === 'microsoft' ? get('tenant_id') : null,
    hosted_domain: type === 'google' ? get('hosted_domain') : null,
    issuer: type === 'oidc' ? get('issuer') : null, authorization_url: type === 'oidc' ? get('authorization_url') : null,
    token_url: type === 'oidc' ? get('token_url') : null, jwks_url: type === 'oidc' ? get('jwks_url') : null,
    userinfo_url: type === 'oidc' ? get('userinfo_url') : null,
  }
}

function providerSection(row: ProviderRow, rows: ProviderRow[], dispatch: Dispatch<ProviderAction>, realm: string,
  editable: boolean, t: ReturnType<typeof useT>) {
  const l = (key: string) => t('secure.keycloak.' + key)
  const { key, value } = row
  const name = (field: string) => 'provider.' + key + '.' + field
  const edit = (fields: Partial<IdentityProvider>) => dispatch({ type: 'edit', key, fields })
  const providerFields = [
    textField(name('alias'), l('alias'), value.alias, {
      max: 31, required: true, checks: [keycloakAlias], controlled: true, change: alias => edit({ alias }),
      validateWith: input => duplicateValue(input.trim(), rows.filter(other => other.key !== key).map(other => other.value.alias.trim())),
    }),
    textField(name('display_name'), l('display_name'), value.display_name, { max: 100, checks: [signInLine] }),
    textField(name('client_id'), l('client_id'), value.client_id, { max: 255, required: true, checks: [keycloakProviderClient] }),
    ...(value.type === 'google' ? [textField(name('hosted_domain'), l('hosted_domain'), value.hosted_domain, {
      max: 255, checks: [orgSsoDomain],
    })] : []),
    ...(value.type === 'microsoft' ? [textField(name('tenant_id'), l('tenant_id'), value.tenant_id, {
      max: 100, required: true, checks: [hookUuid],
    })] : []),
    ...(value.type === 'oidc' ? oidcFields.map(field => textField(name(field), l(field), value[field], {
      max: 2000, required: field !== 'userinfo_url', checks: [keycloakEndpoint],
      type: 'url', controlled: true, change: input => edit({ [field]: input }),
    })) : []),
  ]
  return {
    key, title: t('secure.keycloak.providerTitle', { provider: l(value.type), count: rows.indexOf(row) + 1 }), fields: providerFields,
    extra: <Stack>
      {editable && value.type === 'oidc' && <Discovery disabled={false} onFill={edit} />}
      {value.alias && <Stack gap={1}>
        <p>{l('brokerHelp')} <code>{t('secure.keycloak.brokerPath', { realm, alias: value.alias.trim() })}</code></p>
        <p>{l('secretHelp')} <code>{'KC_IDP_' + value.alias.trim().toUpperCase().replace(/-/g, '_') + '_CLIENT_SECRET'}</code></p>
      </Stack>}
    </Stack>,
    actions: editable && <Row><ConfirmDestructive trigger={<Button variant="danger">{l('removeIdp')}</Button>}
      title={l('removeIdp')} description={l('removeIdpDescription')} action={t('secure.remove')}
      onConfirm={() => dispatch({ type: 'remove', key })} /></Row>,
  }
}

function KeycloakSettings({ id, config, suite, project, editable, reload }: {
  id: string; config: KeycloakConfig | null; suite?: SavedSuite | null; project?: Project; editable: boolean; reload: () => void
}) {
  const t = useT()
  const l = (key: string) => t('secure.keycloak.' + key)
  const saved = config ?? keycloakDefaults
  const [mode, setMode] = useState(saved.mode)
  const [source, setSource] = useState(saved.source_project_id ?? '-')
  const [realm, setRealm] = useState(saved.realm ?? '')
  const [revision, setRevision] = useState(0)
  const [providers, dispatch] = useReducer(providersReducer, saved.identity_providers, providerState)
  const write = useSecureMutation(id, (body: KeycloakWrite) => securityApi.saveKeycloak(id, body))
  const formatDate = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  const shared = Boolean(suite) || mode === 'shared'
  const sources = useQuery({ ...sourceOptions(id), enabled: shared && !suite })
  const slug = project?.slug?.replace(/_/g, '-')
  const derivedRealm = suite ? 'suite-' + suite.suite_id : undefined
  const activeRealm = derivedRealm ?? realm ?? slug
  const sourceChoices = [{ value: '-', label: l('sourceNone') },
    ...(sources.data ?? []).map(item => ({ value: item.id, label: t('secure.keycloak.sourceOption', item) }))]
  if (source !== '-' && !sourceChoices.some(item => item.value === source)) sourceChoices.push({ value: source, label: l('sourceSaved') })
  const number = (name: 'password_min_length' | 'session_idle_minutes' | 'session_max_hours' | 'audit_retention_days', min: number, max: number) =>
    numberField(name, l(name), saved[name], { min, max, integer: true }, true, (value, data) => name === 'session_idle_minutes'
      ? orderedNumber(value, String(readNumber(data, 'session_max_hours') * 60)) : undefined)
  const choices = (values: string[]) => values.map(value => ({ value, label: l(value) }))
  const sections = groups([
    { title: l('location'), fields: [], extra: <Stack gap={2}>
      <Radio name="mode" value="own" label={l('own')} checked={!shared} disabled={!editable || Boolean(suite) || write.isPending}
        onChange={() => setMode('own')} />
      <Radio name="mode" value="shared" label={l('shared')} checked={shared} disabled={!editable || Boolean(suite) || write.isPending}
        onChange={() => setMode('shared')} />
      {suite && <Alert action={<SecureLink id={id} section="suite" label={l('suiteLink')} />}>
        {t('secure.keycloak.suiteLocks', { realm: derivedRealm ?? '', client: project?.slug ?? saved.api_client_id ?? '' })}
      </Alert>}
    </Stack> },
    ...(shared && !suite ? [{ title: l('sharedGroup'), fields: [pickField('source_project_id', l('source'), source, sourceChoices, {
      hint: l('sourceHelp'), change: value => {
        setSource(value)
        const picked = sources.data?.find(item => item.id === value)
        if (picked) setRealm(picked.realm)
      },
    })], extra: sources.isError ? <LoadFailure error={sources.error} message={l('sourceError')} retry={() => void sources.refetch()} /> : null }] : []),
    { title: l('realmGroup'), hint: l('realmDescription'), fields: [
      textField('realm', l('realm'), derivedRealm ?? realm, { max: 63, locked: Boolean(suite), controlled: true, change: setRealm,
        placeholder: slug, hint: l('realmHelp'), checks: [keycloakRealm] }),
      textField('api_client_id', l('api_client_id'), suite ? project?.slug ?? saved.api_client_id : saved.api_client_id, {
        max: 100, locked: Boolean(suite), placeholder: slug && slug + '-api', checks: [keycloakClient],
      }),
      textField('web_client_id', l('web_client_id'), suite ? project?.slug ?? saved.web_client_id : saved.web_client_id, {
        max: 100, locked: Boolean(suite), placeholder: slug && slug + '-web', checks: [keycloakClient],
        validateWith: (value, data) => suite ? undefined : duplicateValue(value.trim() || (slug ? slug + '-web' : ''),
          [readText(data, 'api_client_id') || (slug ? slug + '-api' : '')]),
      }),
      textField('redirect_uris', l('redirect_uris'), saved.redirect_uris.join('\n'), { area: true, checks: [keycloakRedirects],
        hint: l('redirectHelp'), placeholder: l('redirectPlaceholder') }),
    ] },
    ...(!shared ? [{ title: l('security'), fields: [
      number('password_min_length', 8, 128), pickField('mfa', l('mfa'), saved.mfa, choices(['off', 'optional', 'required'])),
      number('session_idle_minutes', 5, 43200), number('session_max_hours', 1, 720), number('audit_retention_days', 7, 3650),
    ], extra: <Row><SecureLink id={id} section="auth" label={t('secure.auth.title')} />
      <SecureLink id={id} section="access" label={t('secure.auth.access')} /></Row> },
    { title: l('providers'), fields: [], extra: <Stack>
      <p>{t('secure.keycloak.providerCount', { count: providers.rows.length })}</p>
      {!providers.rows.length && <p>{l('providersEmpty')}</p>}
      {editable && <Row>{providerTypes.map(kind => <Button key={kind} disabled={providers.rows.length >= 10 || write.isPending}
        onClick={() => dispatch({ type: 'add', kind, label: l(kind) })}>{t('secure.keycloak.addProvider', { provider: l(kind) })}</Button>)}</Row>}
    </Stack> },
    ...providers.rows.map(row => providerSection(row, providers.rows, dispatch, activeRealm || slug || '', editable && !write.isPending, t)),
    ] : []),
  ])
  const aliases = Object.fromEntries(providers.rows.flatMap(({ key }, index) => ['alias', 'display_name', 'client_id',
    'hosted_domain', 'tenant_id', ...oidcFields].map(name => ['identity_providers.' + index + '.' + name, 'provider.' + key + '.' + name])))
  return <Stack gap={4}>
    <WriteNotice error={write.error} message={l(codeOf(write.error) === 'has_dependents' ? 'dependentConflict' : 'saveError')}
      saved={write.isSuccess ? l('saved') : undefined} reload={() => { write.reset(); reload() }} />
    <Form key={revision} {...sections} serverErrors={fieldErrors(write.error, aliases)} submitLabel={t('common.save')}
      pending={write.isPending} readOnly={!editable} submitProps={{ hidden: !editable }}
      actions={<Button disabled={write.isPending} onClick={() => {
        setMode(saved.mode); setSource(saved.source_project_id ?? '-'); setRealm(saved.realm ?? '')
        dispatch({ type: 'reset', providers: saved.identity_providers }); write.reset(); setRevision(value => value + 1)
      }}>{t('common.discard')}</Button>}
      onSubmit={data => {
        const body: KeycloakWrite = {
          mode: shared ? 'shared' : 'own', realm: derivedRealm ?? readNullable(data, 'realm'),
          api_client_id: suite ? project?.slug ?? saved.api_client_id : readNullable(data, 'api_client_id'),
          web_client_id: suite ? project?.slug ?? saved.web_client_id : readNullable(data, 'web_client_id'),
          redirect_uris: readLines(readText(data, 'redirect_uris')),
          password_min_length: shared ? saved.password_min_length : readNumber(data, 'password_min_length'),
          mfa: shared ? saved.mfa : readText(data, 'mfa') as KeycloakWrite['mfa'],
          session_idle_minutes: shared ? saved.session_idle_minutes : readNumber(data, 'session_idle_minutes'),
          session_max_hours: shared ? saved.session_max_hours : readNumber(data, 'session_max_hours'),
          audit_retention_days: shared ? saved.audit_retention_days : readNumber(data, 'audit_retention_days'),
          source_project_id: shared && !suite && source !== '-' ? source : null,
          identity_providers: shared ? [] : providers.rows.map(row => providerBody(row, data)),
        }
        write.mutate(body, { onSuccess: result => {
          setMode(result.mode)
          setSource(result.source_project_id ?? '-')
          setRealm(result.realm)
          dispatch({ type: 'reset', providers: result.identity_providers })
          setRevision(value => value + 1)
        } })
      }} />
    <SettingsSection title={l('topology')}>
      <Grid>{[
        ['realm', activeRealm || slug], ['api_client_id', suite ? project?.slug : saved.api_client_id ?? (slug && slug + '-api')],
        ['web_client_id', suite ? project?.slug : saved.web_client_id ?? (slug && slug + '-web')],
      ].map(([label, value]) => <Card key={label}><Stack gap={1}><strong>{l(label ?? '')}</strong><code>{value || l('automatic')}</code></Stack></Card>)}</Grid>
      {!shared && <Stack gap={1}>
        <p>{t('secure.keycloak.timeline', { idle: saved.session_idle_minutes, maximum: saved.session_max_hours })}</p>
        <Progress label={l('sessionLabel')} value={saved.session_idle_minutes} max={saved.session_max_hours * 60} />
      </Stack>}
      {config?.created_at && config.updated_at && <Grid>
        <Stack gap={1}><strong>{l('createdAt')}</strong><time dateTime={config.created_at}>{formatDate(config.created_at)}</time></Stack>
        <Stack gap={1}><strong>{l('updatedAt')}</strong><time dateTime={config.updated_at}>{formatDate(config.updated_at)}</time></Stack>
      </Grid>}
    </SettingsSection>
    <SettingsSection title={l('deployment')} description={l('deploymentHelp')}>
      <Grid>{[...commonEnvironment, ...(shared ? sharedEnvironment : ownEnvironment)].map(name => <code key={name}>{name}</code>)}</Grid>
      <Stack gap={1}><strong>{l('generated')}</strong>
        {(shared ? ['keycloak/clients.json', 'scripts/keycloak_register.py'] : ['keycloak/realm.json']).map(file => <code key={file}>{file}</code>)}
      </Stack>
    </SettingsSection>
  </Stack>
}

export default function KeycloakScreen(props: SecureProps) {
  const t = useT()
  const l = (key: string) => t('secure.keycloak.' + key)
  const { projectId: id } = props
  const query = useQuery(keycloakOptions(id))
  const auth = useQuery(authOptions(id))
  const metadata = useQuery(projectInfoOptions(id))
  const active = query.data?.active
  const issues = useQuery({ ...projectIssuesOptions(id), enabled: Boolean(active) })
  const findings = (issues.data?.issues ?? []).filter(item => item.path.startsWith('auth.keycloak'))
  const [action, setAction] = useState<'enable' | 'disable'>()
  const [editing, setEditing] = useState(false)
  const [switched, setSwitched] = useState(false)
  const [revision, setRevision] = useState(0)
  const client = useQueryClient()
  const editable = canEdit(props)
  const reload = async () => {
    const result = await Promise.all([query.refetch(), auth.refetch()])
    if (result.every(item => !item.isError)) setRevision(value => value + 1)
  }
  return <Stack gap={4}>
    <PageHeader title={l('title')} description={l('lead')} />
    <SecureRole {...props} />
    {query.isPending || auth.isPending ? <SecureLoading label={l('loading')} />
      : query.isError || auth.isError ? <LoadFailure error={query.error ?? auth.error} message={l('loadError')} retry={() => void reload()} />
      : !query.data && !editing ? <EmptyState title={l('empty')} description={l('emptyDescription')}
        action={editable && <Button variant="primary" onClick={() => setEditing(true)}>{l('configure')}</Button>} />
      : <>
        {switched && <Alert tone="success">{l(active ? 'enabled' : 'disabled')}</Alert>}
        <SettingsSection title={l(active ? 'statusOn' : 'statusOff')} description={l(active ? 'onDescription' : 'offDescription')}>
          {editable && <Row><Button variant={active ? 'danger' : 'primary'} disabled={!query.data}
            title={!query.data ? l('saveFirst') : undefined} onClick={() => {
              const next = active ? 'disable' : 'enable'
              client.removeQueries({ queryKey: impactOptions(id, next).queryKey, exact: true })
              setAction(next); setSwitched(false)
            }}>{l(active ? 'disable' : 'enable')}</Button></Row>}
        </SettingsSection>
        {action && <SwitchProvider id={id} action={action} close={() => setAction(undefined)} reload={() => { setSwitched(true); setAction(undefined) }} />}
        {!!findings.length && <Findings issues={findings} />}
        {issues.isError && <LoadFailure error={issues.error} message={l('issuesError')} retry={() => void issues.refetch()} />}
        <KeycloakSettings key={revision} id={id} config={query.data} suite={auth.data?.suite} project={metadata.data}
          editable={editable} reload={() => void reload()} />
      </>}
  </Stack>
}
