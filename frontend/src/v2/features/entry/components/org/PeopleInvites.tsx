import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../../i18n'
import { ConfirmDestructive, Form, ReadOnlyNote, SettingsSection } from '../../../../patterns'
import { Badge, Button, Row, Select, Stack } from '../../../../ui'
import { entryEmailChecks, entryLimits } from '../../../../validators'
import { orgApi, orgQueries } from '../../api/org'
import type { OrgInvitationCreated, OrgMember, OrgRole } from '../../api/org'
import { useCopy } from '../SecondFactor'
import { canAdmin, orgDate, OrgData, OrgProblem, OrgTabButton, OrgTable, ProjectBack, roles, textValue, useOrgAction, useOrgFields } from './shared'
import type { OrgProps } from './shared'

export function People({ members, ...props }: OrgProps & { members: OrgMember[] }) {
  const { org, user, owners } = props
  const t = useT()
  const action = useOrgAction(props)
  const admin = canAdmin(org)
  const owner = org.my_role === 'owner'
  const invite = <OrgTabButton slug={org.slug} tab="invites">{t('org.inviteSomeone')}</OrgTabButton>
  return <Stack gap={4}>
    {action.isError && <OrgProblem error={action.error} />}
    <OrgTable navigation={props} label={t('org.tab.people')} fields={['name', 'role', 'status', 'lastLogin', 'mfa', 'joined', ...(admin ? ['actions'] : [])]}
      empty={t('org.noMembers')} action={admin ? invite : <ProjectBack />} rows={members.map(member => {
        const editable = admin && member.user_id !== user.id && (owner || member.role !== 'owner')
        return { id: member.user_id, cells: [
          <Stack gap={1}><strong>{member.name || member.email}</strong>{member.name && <span className="v2-muted">{member.email}</span>}</Stack>,
          editable ? <Select value={member.role} disabled={action.isPending} triggerProps={{ 'aria-label': t('org.roleOf', { email: member.email }) }}
            options={roles.filter(role => owner || role !== 'owner').map(role => ({ value: role, label: t('org.role.' + role) }))}
            onValueChange={role => action.submit(() => orgApi.role(org.slug, member.user_id, role as OrgRole), 'org.roleUpdated')} /> :
            t('org.role.' + member.role),
          <Badge>{t('org.status.' + (member.status ?? 'active'))}</Badge>,
          orgDate(member.last_login_at) ?? t('org.na'),
          member.mfa_enabled === undefined ? t('org.na') : t(member.mfa_enabled ? 'org.yes' : 'org.no'),
          orgDate(member.joined_at) ?? t('org.na'),
          editable ? <Row>
            {owner && member.role !== 'owner' && member.status !== 'suspended' && <ConfirmDestructive
              trigger={<Button disabled={action.isPending}>{t('org.makeOwner')}</Button>}
              title={t('org.makeOwnerTitle', { email: member.email })} description={t('org.makeOwnerBody')}
              action={t('org.transferOwnership')} onConfirm={() => action.perform(() => orgApi.transfer(org.slug, member.user_id), 'org.ownerTransferred')} />}
            <ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending}>{t('org.remove')}</Button>}
              title={t('org.removeMemberTitle', { email: member.email, org: org.name })} description={t('org.removeMemberBody')}
              action={t('org.remove')} onConfirm={() => action.perform(() => orgApi.remove(org.slug, member.user_id), 'org.memberRemoved')} />
          </Row> : t('org.na'),
        ] }
      })} />
    {admin ? <SettingsSection title={t('org.manageMembers')} description={t('org.peopleHelp')}>{invite}</SettingsSection> :
      <ReadOnlyNote>{t('org.peopleReadOnly', { owners })}</ReadOnlyNote>}
  </Stack>
}

function remaining(expires: string) {
  const hours = Math.ceil((Date.parse(expires) - Date.now()) / 3_600_000)
  if (!(hours > 0)) return { key: 'org.status.expired', count: 0 }
  return hours >= 24 ? { key: 'org.inviteDays', count: Math.floor(hours / 24) } : { key: 'org.inviteHours', count: hours }
}

export function Invites(props: OrgProps & { paused: boolean }) {
  const { org, search, setSearch, paused } = props
  const t = useT()
  const query = useQuery(orgQueries.invites(org.slug))
  const action = useOrgAction(props)
  const fields = useOrgFields()
  const copy = useCopy()
  const [fresh, setFresh] = useState<OrgInvitationCreated>()
  const [formVersion, resetForm] = useState(0)
  return <Stack gap={4}>
    {action.isError && <OrgProblem error={action.error} />}
    <SettingsSection title={t('org.inviteSomeone')} description={t('org.inviteSeat')}>
      <Form key={formVersion} fields={[
        fields.input('email', { type: 'email', placeholder: t('org.invitePlaceholder'), maxLength: entryLimits.email }, entryEmailChecks),
        fields.select('role', roles.filter(role => org.my_role === 'owner' || role !== 'owner')),
      ]} pending={action.isPending} readOnly={paused || Boolean(fresh)} submitLabel={t('org.invite')}
      onSubmit={data => action.submit(async () => {
        setFresh(await orgApi.invite(org.slug, textValue(data, 'email'), textValue(data, 'role') as OrgRole))
        resetForm(value => value + 1)
      }, '')} />
      {paused && <OrgTabButton slug={org.slug} tab="plan">{t('org.seePlans')}</OrgTabButton>}
    </SettingsSection>
    {fresh && <SettingsSection title={t('org.inviteLink')} description={t(fresh.emailed ? 'org.inviteEmailed' : 'org.inviteManual', { email: fresh.email })}>
      <code>{fresh.invite_url}</code>
      <Row><Button onClick={() => void copy(fresh.invite_url, 'org.copied')}>{t('org.copyLink')}</Button>
        <Button onClick={() => setFresh(undefined)}>{t('org.inviteSent')}</Button></Row>
    </SettingsSection>}
    <OrgData query={query}>{data => {
      const pending = data.items.filter(invite => invite.status === 'pending')
      const past = data.items.filter(invite => invite.status !== 'pending')
      const rows = search.past ? [...pending, ...past] : pending
      return <SettingsSection title={t('org.pendingInvites')} description={t('org.lostLink')}>
        <OrgTable navigation={props} label={t('org.pendingInvites')} fields={['email', 'role', 'status', 'created', 'expires', 'actions']}
          empty={t('org.noInvites')} rows={rows.map(invite => {
            const expiry = remaining(invite.expires_at)
            return { id: invite.id, cells: [
              invite.email, t('org.role.' + invite.role), <Badge>{t('org.status.' + invite.status)}</Badge>,
              orgDate(invite.created_at), <Stack gap={1}>
                {orgDate(invite.expires_at)}
                {invite.status === 'pending' && <span className="v2-muted">{t(expiry.key, { count: expiry.count })}</span>}
              </Stack>,
              <Row>{(invite.status === 'pending' || invite.status === 'expired') && (invite.role !== 'owner' || org.my_role === 'owner') && <ConfirmDestructive
                trigger={<Button disabled={action.isPending || Boolean(fresh)}>{t('org.resend')}</Button>}
                title={t('org.resendTitle', { email: invite.email })} description={t('org.lostLink')}
                action={t('org.resend')} onConfirm={() => action.perform(async () => {
                  setFresh(await orgApi.resend(org.slug, invite.id))
                }, '')} />}
              {invite.status === 'pending' && <ConfirmDestructive trigger={<Button variant="danger" disabled={action.isPending}>{t('org.revoke')}</Button>}
                title={t('org.revokeTitle', { email: invite.email })} description={t('org.revokeBody')} action={t('org.revoke')}
                onConfirm={() => action.perform(() => orgApi.revoke(org.slug, invite.id), 'org.inviteRevoked')} />}</Row>,
            ] }
          })} />
        {past.length > 0 && <Row><Button onClick={() => setSearch({ tab: 'invites', past: search.past ? undefined : true })}>
          {t(search.past ? 'org.hidePast' : 'org.showPast', { count: past.length })}
        </Button></Row>}
      </SettingsSection>
    }}</OrgData>
  </Stack>
}
