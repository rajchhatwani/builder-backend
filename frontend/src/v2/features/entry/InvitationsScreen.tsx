import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId } from 'react'
import { useLanguage, useT } from '../../i18n'
import { Form, PageHeader, ReadOnlyNote } from '../../patterns'
import { Badge, Button, EmptyState, Input, Row, Skeleton, Stack, Table, useToast } from '../../ui'
import { checkInviteLink, inviteTokenFrom } from '../../validators'
import {
  entryApi, entryError, entryKeys, invitationsOptions, organizationsOptions, useCustomerSession, useEntryAction,
} from './api/entry'
import type { InvitationTarget } from './api/entry'
import { EntryCard, EntryProblem } from './components/EntryFrame'
import { ResendVerification } from './components/ResendVerification'
import { valueOf } from './components/fields'
import { invitationProblemValues, inviteProblem } from './components/messages'
import { clearEntryInvitation, entryInvitation } from './entryLinks'

export default function InvitationsScreen() {
  const t = useT()
  const { language } = useLanguage()
  const { data: user } = useCustomerSession()
  const client = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const accept = useEntryAction()
  const pasteHeading = useId()
  const userId = user?.id ?? ''
  const verified = Boolean(user?.email_verified_at)
  const pending = useQuery(invitationsOptions(userId, verified))
  const organizations = useQuery({ ...organizationsOptions(userId), enabled: !!userId })
  const landing = entryInvitation()
  const validLanding = landing && !checkInviteLink(landing)
  const dates = new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeZone: 'UTC' })
  const today = Date.now()

  function join(target: InvitationTarget) {
    accept.run(async () => {
      const result = await entryApi.acceptInvitation(target)
      const alreadyJoined = organizations.data?.items.some(org => org.id === result.id)
      clearEntryInvitation()
      const keys = [entryKeys.invitations(userId), entryKeys.organizations(userId), entryKeys.session()]
      for (const queryKey of keys) void client.invalidateQueries({ queryKey })
      client.setQueryData(entryKeys.organization(userId, result.slug), result)
      toast({ title: t(alreadyJoined ? 'entry.alreadyMember' : 'entry.joined', { org: result.name }), tone: 'success' })
      void navigate({ to: '/org/$slug', params: { slug: result.slug }, replace: true })
    })
  }

  if (!user) return null

  const rows = pending.data?.items ?? []
  const columns = ['organization', 'role', 'expires', 'actions'].map(id => ({ id, label: t(`entry.${id}`) }))
  const { status, code } = entryError(accept.error)
  const values = invitationProblemValues(accept.error, user.email)
  const acceptMessage = t(code === 'seat_limit' && 'plan' in values ? 'entry.seatLimitDetail' : inviteProblem(accept.error), values)
  const list = !verified ? <Stack>
    <ReadOnlyNote>{t('entry.verifyInvitations')}</ReadOnlyNote>
    <ResendVerification initialEmail={user.email} />
  </Stack> : pending.isPending ? <Skeleton label={t('entry.loadingInvites')} lines={5} />
    : pending.isError ? <EntryProblem error={pending.error} message={t(inviteProblem(pending.error), { email: user.email })}
        retry={() => void pending.refetch()} />
    : rows.length === 0 ? <EmptyState title={t('entry.noInvites', { email: user.email })}
        action={<Button asChild><a href={`#${pasteHeading}`}>{t('entry.haveLink')}</a></Button>} />
    : <Stack>
        <Table label={t('entry.waiting')} columns={columns} rows={rows.map(invite => {
          const organization = invite.organization_name || invite.organization_slug
          const expires = new Date(invite.expires_at)
          const created = new Date(invite.created_at)
          const days = Math.max(0, Math.ceil((expires.getTime() - today) / 86_400_000))
          return { id: invite.id, cells: [
            organization,
            <Stack gap={1}><span>{t(`entry.roles.${invite.role}`)}</span><span className="v2-muted">{t(`entry.roleHelp.${invite.role}`)}</span></Stack>,
            <Stack gap={1}>
              <span>{t('entry.expiry', { date: dates.format(expires), count: days })}</span>
              <Row gap={2}><Badge>{t('entry.invitePending')}</Badge><span className="v2-muted">{t('entry.inviteSent', { date: dates.format(created) })}</span></Row>
            </Stack>,
            <Button disabled={accept.isPending || pending.isFetching} onClick={() => join({ by: 'id', value: invite.id })}
              aria-label={t('entry.acceptOrg', { org: organization })}>{t('entry.accept')}</Button>,
          ] }
        })} />
        <p className="v2-muted">{t('entry.invitesFootnote', { email: user.email })}</p>
      </Stack>

  return <Stack gap={5}>
    <PageHeader title={t('entry.invitations')} description={t('entry.invitesDescription', { email: user.email })} />
    {accept.isError && <EntryProblem error={accept.error} message={acceptMessage}
      retry={status === 409 ? () => void pending.refetch().then(() => accept.reset()) : undefined} />}
    {landing && <EntryCard title={t('entry.inviteLanding')}>
      <p>{t('entry.inviteLandingHint')}</p>
      {validLanding ? <Row><Button variant="primary" disabled={accept.isPending}
        onClick={() => join({ by: 'token', value: landing })}>{t(accept.isPending ? 'entry.joining' : 'entry.acceptInvite')}</Button></Row>
        : <ReadOnlyNote>{t('validation.inviteLink')}</ReadOnlyNote>}
    </EntryCard>}
    <EntryCard>
      <h2 id={pasteHeading} tabIndex={-1}>{t('entry.haveLink')}</h2>
      <Form fields={[{
        name: 'invitation', label: t('entry.inviteLink'), validate: [checkInviteLink],
        control: attributes => <Input {...attributes} required placeholder={t('entry.invitePlaceholder')} autoComplete="off" />,
      }]} pending={accept.isPending} submitLabel={t(accept.isPending ? 'entry.joining' : 'entry.join')}
        onSubmit={values => join({ by: 'token', value: inviteTokenFrom(valueOf(values, 'invitation')) })} />
    </EntryCard>
    <EntryCard title={t('entry.waiting')}>{list}</EntryCard>
  </Stack>
}
