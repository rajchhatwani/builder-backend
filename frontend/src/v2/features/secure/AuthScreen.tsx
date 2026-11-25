import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { AuthConfig, AuthConfigUpdate } from '../../../api/types'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form, PageHeader, SettingsSection } from '../../patterns'
import { Alert, Button, Card, EmptyState, Grid, Stack, Tabs } from '../../ui'
import { signInLine, signInObject, signInRate, signInSmsSender, validators } from '../../validators'
import { authOptions, checksOptions, codeOf, fieldErrors, projectIssuesOptions, securityApi, useSecureMutation } from './api/security'
import AuthFields from './AuthFields'
import { canEdit, checkField, Findings, groups, LoadFailure, numberField, pickField, readNullable,
  readNumber, readText, requiredWhen, SecureLink, SecureLoading, SecureRole, textField, useSecureSearch, WriteNotice } from './SecureForm'
import type { SecureProps } from './SecureForm'

const smtpAliases = Object.fromEntries(['host', 'port', 'from_email', 'from_name'].map(key => ['smtp_config.' + key, key]))
const rateKeys = ['login_rate_limit', 'register_rate_limit', 'reset_rate_limit'] as const
const fromEnabled = (data: FormData, key: string) => data.has(key)

function settingsBody(data: FormData, original: AuthConfig, smtpRequired: boolean): AuthConfigUpdate {
  const builtin = original.provider === 'builtin'
  const sms = builtin && fromEnabled(data, 'sms_otp_enabled')
  const host = readText(data, 'host')
  const app = readNullable(data, 'app_name')
  const templates = readNullable(data, 'email_templates')
  const shared: AuthConfigUpdate = {
    enabled: fromEnabled(data, 'enabled'),
    access_token_ttl_minutes: readNumber(data, 'access_token_ttl_minutes'),
    email_verification_required: fromEnabled(data, 'email_verification_required'),
    smtp_config: smtpRequired || host ? {
      host, port: readNumber(data, 'port'), from_email: readText(data, 'from_email'),
      from_name: readText(data, 'from_name'), use_tls: fromEnabled(data, 'use_tls'),
    } : original.smtp_config,
    invite_only: fromEnabled(data, 'invite_only'),
    multi_tenant: fromEnabled(data, 'multi_tenant'),
    security_headers_enabled: fromEnabled(data, 'security_headers_enabled'),
    app_name: app, email_templates: templates ? JSON.parse(templates) as Record<string, unknown> : null,
  }
  if (!builtin) return { ...shared, email_magic_link_enabled: false, sms_otp_enabled: false }
  return {
    ...shared,
    deletion_mode: readText(data, 'deletion_mode') as AuthConfig['deletion_mode'],
    token_store: readText(data, 'token_store') as AuthConfig['token_store'],
    refresh_token_ttl_days: readNumber(data, 'refresh_token_ttl_days'),
    jwt_algorithm: readText(data, 'jwt_algorithm') as AuthConfig['jwt_algorithm'],
    email_magic_link_enabled: fromEnabled(data, 'email_magic_link_enabled'),
    sms_otp_enabled: sms,
    sms_provider: sms ? readText(data, 'sms_provider') as AuthConfig['sms_provider'] : null,
    sms_config: sms ? { from_number: readText(data, 'from_number') } : null,
    otp_ttl_minutes: readNumber(data, 'otp_ttl_minutes'),
    ...Object.fromEntries(rateKeys.map(key => [key, readText(data, key)])),
    app_url: readNullable(data, 'app_url'),
  }
}

function Settings({ projectId, config, editable, reload }: {
  projectId: string; config: AuthConfig; editable: boolean; reload: () => void
}) {
  const t = useT()
  const l = (key: string) => t('secure.auth.' + key)
  const [magic, setMagic] = useState(config.email_magic_link_enabled)
  const [verify, setVerify] = useState(config.email_verification_required)
  const [sms, setSms] = useState(config.sms_otp_enabled)
  const [sender, setSender] = useState(config.sms_provider ?? '')
  const [invite, setInvite] = useState(config.invite_only)
  const [tenant, setTenant] = useState(config.multi_tenant)
  const [accessTtl, setAccessTtl] = useState(String(config.access_token_ttl_minutes))
  const [enabled, setEnabled] = useState(config.enabled)
  const [pendingConfirmation, setConfirmation] = useState<AuthConfigUpdate>()
  const [revision, setRevision] = useState(0)
  const builtin = config.provider === 'builtin'
  const smtpRequired = verify || (builtin && (magic || invite || tenant))
  const smtp = config.smtp_config
  const setup = useSecureMutation(projectId, ({ body, confirm }: { body: AuthConfigUpdate; confirm?: boolean }) => securityApi.update(projectId, body, confirm))
  const checks = useQuery({ ...checksOptions(projectId), enabled: false })
  const projectStatus = useQuery({ ...projectIssuesOptions(projectId), enabled: !editable })
  const reset = () => {
    setMagic(config.email_magic_link_enabled); setVerify(config.email_verification_required); setSms(config.sms_otp_enabled)
    setSender(config.sms_provider ?? ''); setInvite(config.invite_only); setTenant(config.multi_tenant); setEnabled(config.enabled)
    setAccessTtl(String(config.access_token_ttl_minutes)); setup.reset(); setRevision(value => value + 1)
  }
  const save = async (body: AuthConfigUpdate, confirm = false) => {
    try {
      await setup.mutateAsync({ body, confirm })
      if (checks.data) void checks.refetch()
    } catch (error) {
      if (!confirm && codeOf(error) === 'access_weakened') setConfirmation(body)
      else if (confirm) throw error
    }
  }
  const radioOptions = (values: readonly string[]) => values.map(value => ({ value, label: l(value) }))
  const fmt = (name: string, value: number, min: number, max: number, label = name) =>
    numberField(name, l(label), value, { min, max, integer: true })
  const chk = (name: string, checked: boolean, change?: (next: boolean) => void) => checkField(name, l(name), checked, change)
  const visibleSmtp = smtpRequired || !builtin || Boolean(smtp)
  const sections = groups([
    { title: l('general'), fields: [chk('enabled', enabled, setEnabled), ...(builtin ? [
      pickField('deletion_mode', l('deletion_mode'), config.deletion_mode, radioOptions(['soft', 'hard']), { hint: l('deletionHelp') }),
    ] : [])] },
    { title: l('tokens'), fields: [
      ...(builtin ? [pickField('token_store', l('token_store'), config.token_store, radioOptions(['db', 'redis']))] : []),
      textField('access_token_ttl_minutes', l(builtin ? 'access_token_ttl_minutes' : 'accessKeycloak'), accessTtl, {
        type: 'number', required: true, checks: [validators.number({ min: 1, max: 1440, integer: true })],
        controlled: true, change: setAccessTtl,
      }),
      ...(builtin ? [fmt('refresh_token_ttl_days', config.refresh_token_ttl_days, 1, 365),
        pickField('jwt_algorithm', l('jwt_algorithm'), config.jwt_algorithm, radioOptions(['HS256', 'RS256']))] : []),
    ] },
    { title: l('email'), fields: [
      ...(builtin ? [chk('email_magic_link_enabled', magic, setMagic)] : []),
      chk('email_verification_required', verify, setVerify),
      ...(visibleSmtp ? [
        textField('host', l('host'), smtp?.host, { max: 255, required: smtpRequired, checks: [validators.host], placeholder: l('hostPlaceholder') }),
        fmt('port', smtp?.port ?? 587, 1, 65535),
        textField('from_email', l('from_email'), smtp?.from_email, { max: 255, required: smtpRequired,
          type: 'email', checks: [requiredWhen(Boolean(smtp)), validators.email],
          validateWith: (value, data) => requiredWhen(Boolean(readText(data, 'host')))(value), placeholder: l('emailPlaceholder') }),
        textField('from_name', l('from_name'), smtp?.from_name, { max: 100, required: smtpRequired, checks: [requiredWhen(Boolean(smtp))], validateWith: (value, data) => requiredWhen(Boolean(readText(data, 'host')))(value) }),
        chk('use_tls', smtp?.use_tls ?? true),
      ] : []),
      textField('email_templates', l('email_templates'), config.email_templates ? JSON.stringify(config.email_templates, null, 2) : '',
        { area: true, checks: [signInObject], hint: l('templatesHelp') }),
    ] },
    ...(builtin ? [{ title: l('sms'), fields: [
      chk('sms_otp_enabled', sms, setSms), ...(sms ? [
        pickField('sms_provider', l('sms_provider'), sender, radioOptions(['twilio', 'aws_sns', 'vonage']), {
          change: setSender, required: true, placeholder: l('smsPlaceholder'),
        }),
        textField('from_number', l('from_number'), config.sms_config?.from_number, {
          type: 'tel', max: 20, required: true, checks: [signInSmsSender(sender)], placeholder: l('numberPlaceholder'),
        }),
      ] : []), fmt('otp_ttl_minutes', config.otp_ttl_minutes, 1, 60),
    ] }] : []),
    { title: l('registration'), hint: l(builtin ? 'registrationHelp' : 'registrationKeycloak'), fields: [
      chk('invite_only', invite, setInvite), {
        ...chk('multi_tenant', tenant, setTenant),
        validateWith: () => builtin && invite && tenant ? { key: 'validation.signInTenancy' } : undefined,
      },
    ], extra: <Stack gap={1}><SecureLink id={projectId} section="access" label={l('access')} />
      <SecureLink id={projectId} section="suite" label={t('secure.suite.title')} /></Stack> },
    ...(builtin ? [{ title: l('rateLimits'), fields: rateKeys.map(key => textField(key, l(key), config[key], {
      max: 50, required: true, checks: [signInRate], hint: l('rateHelp'),
    })) }] : []),
    { title: l('branding'), fields: [chk('security_headers_enabled', config.security_headers_enabled),
      textField('app_name', l('app_name'), config.app_name, { max: 100, checks: [signInLine] }),
      ...(builtin ? [textField('app_url', l('app_url'), config.app_url, { max: 2000, checks: [validators.url],
        required: smtpRequired, placeholder: l('appPlaceholder') })] : []),
    ] },
  ])
  const issues = (checks.data?.issues ?? projectStatus.data?.issues ?? [])
    .filter(item => item.path === 'auth' || item.path.startsWith('auth.') || item.path.startsWith('auth['))
  return <Stack gap={4}>
    {!builtin && <Alert action={<SecureLink id={projectId} section="keycloak" label={t('secure.keycloak.title')} />}>{l('keycloakManaged')}</Alert>}
    {!pendingConfirmation && codeOf(setup.error) !== 'access_weakened' && <WriteNotice error={setup.error} message={l('saveError')} saved={setup.isSuccess ? l('saved') : undefined}
      reload={() => { setup.reset(); reload() }} />}
    <ConfirmDestructive open={Boolean(pendingConfirmation)} onOpenChange={open => { if (!open) setConfirmation(undefined) }}
      title={l('weakenTitle')} description={l('weakenDescription')} action={l('weakenAction')}
      onConfirm={async () => {
        if (pendingConfirmation) await save(pendingConfirmation, true)
        setConfirmation(undefined)
      }} />
    <Form key={revision} {...sections} submitLabel={t('common.save')} pending={setup.isPending}
      readOnly={!editable} submitProps={{ hidden: !editable }} serverErrors={fieldErrors(setup.error, { ...smtpAliases, 'sms_config.from_number': 'from_number' })}
      onSubmit={data => { void save(settingsBody(data, config, smtpRequired)) }}
      actions={<Button disabled={setup.isPending} onClick={reset}>{t('common.discard')}</Button>} />
    <SettingsSection title={l('checks')}>
      {!editable && !checks.data && <p>{l('checksEditor')}</p>}
      {editable && <Button disabled={checks.isFetching} onClick={() => void checks.refetch()}>{l('checkAgain')}</Button>}
      {checks.isFetching && <p role="status">{l('checking')}</p>}
      {checks.error && <LoadFailure error={checks.error} message={l('checksError')} />}
      {checks.data && !issues.length && <Alert tone="success">{l('checksClear')}</Alert>}
      {!!issues.length && <Findings issues={issues} />}
    </SettingsSection>
    <SettingsSection title={l('flow')}>
      <Grid>{[
        ['registration', invite ? 'flowInvite' : tenant ? 'flowTenant' : 'flowSignup'],
        ['email_verification_required', verify ? 'flowRequired' : 'flowOptional'],
        ['title', enabled ? builtin ? 'builtin' : 'keycloak' : 'flowOff'],
      ].map(([label, value]) => <Card key={label}><Stack gap={1}><strong>{l(label)}</strong><span>{l(value)}</span></Stack></Card>)}
        <Card><Stack gap={1}><strong>{l('flowToken')}</strong><span>{t('secure.auth.flowTokenTime', {
          minutes: accessTtl && Number.isFinite(Number(accessTtl)) ? new Intl.NumberFormat().format(Number(accessTtl)) : '—',
        })}</span></Stack></Card>
      </Grid>
    </SettingsSection>
  </Stack>
}

export default function AuthScreen(props: SecureProps) {
  const t = useT()
  const l = (key: string) => t('secure.auth.' + key)
  const { projectId } = props
  const { search, tab } = useSecureSearch()
  const query = useQuery(authOptions(projectId))
  const create = useSecureMutation(projectId, () => securityApi.setup(projectId))
  const editable = canEdit(props)
  const [revision, setRevision] = useState(0)
  const reload = async () => {
    const result = await query.refetch()
    if (!result.isError) setRevision(value => value + 1)
  }
  return <Stack gap={4}>
    <PageHeader title={l('title')} description={l('lead')} />
    <SecureRole {...props} />
    <Tabs label={l('title')} value={search.tab === 'fields' ? 'fields' : 'settings'} onChange={tab} items={[
      { id: 'settings', label: l('settings'), content: query.isPending ? <SecureLoading label={l('loading')} />
        : query.isError ? <LoadFailure error={query.error} message={l('loadError')} retry={() => void reload()} />
        : query.data ? <><WriteNotice error={undefined} message={l('setupError')} saved={create.isSuccess ? l('created') : undefined} />
          <Settings key={revision} projectId={projectId} config={query.data} editable={editable} reload={() => void reload()} /></>
        : <Stack>
          <WriteNotice error={create.error} message={l('setupError')} reload={() => { create.reset(); void reload() }} />
          <EmptyState title={l('empty')} description={l('emptyDetail')} action={editable && <Button variant="primary"
            disabled={create.isPending} onClick={() => create.mutate()}>{l('setup')}</Button>} />
        </Stack> },
      { id: 'fields', label: l('fields'), content: <AuthFields {...props} key={projectId} auth={query.data} /> },
    ]} />
  </Stack>
}
