import { useNavigate } from '@tanstack/react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useLanguage, useT } from '../../i18n'
import { ConfirmDestructive, Form, PageHeader, ReadOnlyNote, SettingsSection } from '../../patterns'
import { Alert, Button, Row, Select, Skeleton, Stack, useToast } from '../../ui'
import { validators } from '../../validators'
import { accountApi } from './api/account'
import { clearCustomerQueries, organizationsOptions, useCustomerSession, useEntryAction, useSetCustomer } from './api/entry'
import type { UserAccount } from './api/entry'
import { AccountMfa } from './components/AccountMfa'
import { AccountPassword } from './components/AccountPassword'
import { AccountTokens } from './components/AccountTokens'
import { EntryProblem } from './components/EntryFrame'
import { ResendVerification } from './components/ResendVerification'
import { formatEntryDate } from './components/entryData'
import { valueOf } from './components/fields'
import { authProblem } from './components/messages'
import { clearEntryInvitation } from './entryLinks'
import './components/customer.css'

function Profile({ user }: { user: UserAccount }) {
  const t = useT()
  const { language } = useLanguage()
  const toast = useToast()
  const setCustomer = useSetCustomer()
  const organizations = useQuery(organizationsOptions(user.id))
  const save = useMutation({
    mutationFn: accountApi.setDefaultOrganization,
    onSuccess: next => {
      setCustomer(next)
      toast({ title: t('account.defaultSaved'), tone: 'success' })
    },
  })
  const [verify, setVerify] = useState(false)
  const facts = [
    { label: t('account.displayName'), value: user.name || t('account.unset') },
    { label: t('account.accountStatus'), value: t(`account.status.${user.status}`) },
    { label: t('account.created'), value: formatEntryDate(user.created_at, language, t('account.unset')) },
    { label: t('account.lastSignIn'), value: formatEntryDate(user.last_login_at, language, t('account.never')) },
    { label: t('account.verification'), value: t(user.email_verified_at ? 'account.confirmed' : 'account.unconfirmed') },
  ]
  return <SettingsSection title={t('account.profile')}>
    <dl className="v2-account-facts">{facts.map(fact => <div key={fact.label}><dt className="v2-muted">{fact.label}</dt><dd>{fact.value}</dd></div>)}</dl>
    {!user.email_verified_at && <Stack>
      <Alert tone="warning" action={<Button onClick={() => setVerify(current => !current)} aria-expanded={verify}>{t('account.verifyAction')}</Button>}>
        {t('account.verifyNotice')}
      </Alert>
      {verify && <ResendVerification initialEmail={user.email} />}
    </Stack>}
    {organizations.isPending ? <Skeleton lines={2} label={t('projectCreate.loading')} /> : organizations.isError
      ? <EntryProblem error={organizations.error} message={t('projectCreate.ownersFailed')} retry={() => void organizations.refetch()} />
      : organizations.data.items.length ? <Stack>
        {save.isError && <EntryProblem error={save.error} message={t(authProblem(save.error))} />}
        <Form key={user.default_organization_id} fields={[{
          name: 'organization', label: t('account.defaultOrg'), hint: t('account.defaultOrgHelp'), validate: [validators.required],
          control: attributes => <Select triggerProps={attributes} name={attributes.name} disabled={attributes.disabled}
            defaultValue={user.default_organization_id ?? undefined} placeholder={t('account.chooseOrg')} required
            options={organizations.data.items.map(item => ({ value: item.id, label: item.name }))} />,
        }]} onSubmit={data => {
          const organization = valueOf(data, 'organization')
          if (organization && organization !== user.default_organization_id) save.mutate(organization)
        }} pending={save.isPending} submitLabel={t('common.save')} />
      </Stack> : <ReadOnlyNote>{t('account.noOrg')}</ReadOnlyNote>}
  </SettingsSection>
}

export default function AccountScreen() {
  const t = useT()
  const { data: user } = useCustomerSession()
  const client = useQueryClient()
  const navigate = useNavigate()
  const logout = useEntryAction()
  if (!user) return null

  return <Stack gap={5}>
    <PageHeader title={t('account.title')} description={user.platform_role !== 'customer'
      ? t('account.staffEmail', { email: user.email }) : user.email} />
    <Profile user={user} />
    <SettingsSection title={t('entry.password')}><AccountPassword user={user} /></SettingsSection>
    <AccountMfa />
    <AccountTokens user={user} />
    <SettingsSection title={t('account.sessions')} description={t('account.sessionHelp')}>
      {logout.isError && <EntryProblem error={logout.error} message={t(authProblem(logout.error))} />}
      <Row><ConfirmDestructive trigger={<Button variant="danger" disabled={logout.isPending}>{t('account.logoutAll')}</Button>}
        title={t('account.logoutTitle')} description={t('account.logoutHelp')} action={t('account.logoutAll')}
        onConfirm={() => logout.run(async () => {
          await accountApi.logoutEverywhere()
          clearEntryInvitation()
          clearCustomerQueries(client)
          void navigate({ to: '/login', search: {}, replace: true })
        })} /></Row>
    </SettingsSection>
  </Stack>
}
