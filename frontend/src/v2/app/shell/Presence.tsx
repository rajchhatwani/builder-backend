import type { RefObject } from 'react'
import type { useProjectLive } from '../../features/projects/api/live'
import { useLanguage, useT } from '../../i18n'
import { ListRow } from '../../patterns'
import { isProjectSection } from '../../projectNavigation'
import { Badge, Button, Row, Sheet, Stack } from '../../ui'

export function Presence({ status, users, user, open, onOpenChange, returnFocus }: ReturnType<typeof useProjectLive> & {
  user: string; open: boolean; onOpenChange: (open: boolean) => void; returnFocus?: RefObject<HTMLElement | null>
}) {
  const t = useT()
  const { language } = useLanguage()
  const others = users.filter(item => item.user_id !== user)
  const roster = others.slice(0, 3).map(item => item.display)
  const live = t('shell.live.' + status)
  return <Row gap={2}>
    <Sheet title={t('shell.presence')} open={open} onOpenChange={onOpenChange} returnFocus={returnFocus}
      trigger={!returnFocus ? <Button aria-label={t('shell.presenceLabel', { status: live })}>
      <Badge tone={status === 'live' ? 'success' : 'neutral'}>{live}</Badge>
    </Button> : undefined}>
      <Stack>{others.length ? others.map(item => <ListRow key={item.user_id}
        title={t('common.serverText', { text: item.display })}
        detail={t(item.where && isProjectSection(item.where) ? 'nav.' + item.where : 'shell.presence')} />) : <p>{t('shell.noPresence')}</p>}</Stack>
    </Sheet>
    {!returnFocus && roster.length > 0 && <span className="v2-presence-roster">{t('shell.alsoHere', { names: new Intl.ListFormat(language).format(roster), extra: others.length > 3 ? t('shell.morePeople', { count: others.length - 3 }) : '' })}</span>}
  </Row>
}
