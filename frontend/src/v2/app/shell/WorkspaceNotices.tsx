import { Link, useRouterState } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { subscribeWorkspaceNotices } from '../../features/projects/api/workspace'
import type { WorkspaceNotice } from '../../features/projects/api/workspace'
import { useT } from '../../i18n'
import { Button, Dialog } from '../../ui'

export function WorkspaceNotices({ organization }: { organization?: string }) {
  const t = useT()
  const pathname = useRouterState({ select: state => state.location.pathname })
  const [notice, setNotice] = useState<WorkspaceNotice>()
  useEffect(() => { setNotice(undefined); return subscribeWorkspaceNotices(setNotice) }, [pathname])
  if (!notice) return null
  const slug = notice.detail?.organization_slug || organization

  if (notice.kind === 'quota') {
    const detail = notice.detail
    const reason = detail?.reason ?? 'cap'
    const resource = t(detail ? 'shell.quota.resource.' + detail.resource : 'shell.quota.resource.generic')
    return <Dialog open onOpenChange={open => { if (!open) setNotice(undefined) }}
      title={t('shell.quota.title.' + reason)}
      description={detail ? t('shell.quota.body.' + reason, { resource, plan: detail.plan, cap: detail.cap ?? 0 }) : t('projectCreate.quotaFallback')}
      closeLabel={t('projectCreate.notNow')} actions={slug && <Button asChild>
        <Link to="/org/$slug" params={{ slug }} search={{ tab: 'plan' }} onClick={() => setNotice(undefined)}>{t('projectCreate.seePlans')}</Link>
      </Button>}>{null}</Dialog>
  }
  return <Dialog open onOpenChange={open => { if (!open) setNotice(undefined) }}
    title={t(notice.kind === 'locked' ? 'shell.lockedTitle' : 'shell.mfaTitle')}
    description={t(notice.kind === 'locked' ? 'shell.lockedBody' : notice.detail?.mfa_enabled ? 'shell.mfaSession' : 'shell.mfaBody')}
    actions={notice.kind === 'mfa' ? <Button asChild><Link to="/account">{t('account.title')}</Link></Button>
      : <Button asChild>{slug ? <Link to="/org/$slug" params={{ slug }}>{t('shell.organization')}</Link>
        : <Link to="/projects">{t('status.back')}</Link>}</Button>}>{null}</Dialog>
}
