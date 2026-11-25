import { Link } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { Badge, Stack } from '../../ui'
import { invitationsOptions, organizationOptions, organizationsOptions, useCustomerSession } from './api/entry'

export function EntryNavigation() {
  const t = useT()
  const client = useQueryClient()
  const { data: user } = useCustomerSession()
  const invitations = useQuery(invitationsOptions(user?.id ?? '', Boolean(user?.email_verified_at)))
  const organizations = useQuery({ ...organizationsOptions(user?.id ?? ''), enabled: !!user })
  if (!user || user.must_change_password) return null
  const count = invitations.data?.total ?? 0
  const prefetchInvitations = () => {
    if (user.email_verified_at) void client.prefetchQuery(invitationsOptions(user.id, true))
  }
  return <nav className="v2-nav" aria-label={t('entry.customerNavigation')}>
    <Stack gap={0}>
      <Link to="/projects" activeOptions={{ exact: true }}>{t('shell.projects')}</Link>
      {(count > 0 || !user.email_verified_at) && <Link to="/invitations" activeOptions={{ exact: true }}
        onMouseEnter={prefetchInvitations} onFocus={prefetchInvitations}>
        {t('entry.invitations')}{count > 0 && <Badge>{t('entry.inviteCount', { count })}</Badge>}
      </Link>}
      {organizations.data?.items.map(organization => {
        const prefetch = () => void client.prefetchQuery(organizationOptions(user.id, organization.slug))
        return <Link key={organization.id} to="/org/$slug" params={{ slug: organization.slug }}
          onMouseEnter={prefetch} onFocus={prefetch}>{organization.name}</Link>
      })}
    </Stack>
  </nav>
}
