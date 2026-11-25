import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useId } from 'react'
import type { ReactNode } from 'react'
import { useLanguage } from '../../../i18n'
import { Alert, Card, EmptyState, Field, Row, Select, Stack } from '../../../ui'
import type { LiveSession, PreviewCredential, PreviewInstance } from '../api/liveWebhooks'
import { isPlatformPreview, platformPreviewsOptions } from '../api/platform'
import { BlockLoad, SectionLink } from './BlockStatus'

export type PlatformPreviewProps = {
  credentials?: Record<string, PreviewCredential>
  renderIdentity?: (preview: PreviewInstance, credential: PreviewCredential) => ReactNode
}

export function PlatformPreview({ id, credentials = {}, renderIdentity, updatedAt, children }: PlatformPreviewProps & {
  id: string; updatedAt?: string | null; children: (session: LiveSession) => ReactNode
}) {
  const { t, language } = useLanguage()
  const scope = useId()
  const search = useSearch({ strict: false })
  const navigate = useNavigate({ from: '/projects/$projectId/$section' })
  const previews = useQuery(platformPreviewsOptions(id))
  const usable = previews.data?.filter(item => isPlatformPreview(id, item)) ?? []
  const target = search.preview ? usable.find(item => item.id === search.preview) : usable.find(item => credentials[item.id]) ?? usable[0]
  const credential = target && credentials[target.id]
  const open = <SectionLink projectId={id} section="see" preview={target?.id ?? search.preview}
    workspace={search.workspace} label={t(target ? 'connectA2.preview.open' : 'connectB.platform.start')} />
  if (!previews.data || previews.isError) return <BlockLoad error={previews.error} retry={() => void previews.refetch()} errorKey="connectA2.preview.loadError" />
  if (!usable.length) return <EmptyState title={t('connectB.platform.none')} description={t('connectB.platform.noneHelp')} action={open} />
  const time = (date: string) => new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(date))
  return <Stack>
    <Card><Stack>
      <Field label={t('connectA2.preview.select')}>{attrs => <Select triggerProps={attrs} value={target?.id ?? ''}
        placeholder={t('connectB.platform.selectPreview')} options={usable.map(item => ({
          value: item.id, label: t('connectA2.preview.item', { id: item.id.slice(0, 8), date: time(item.created_at) }),
        }))} onValueChange={preview => void navigate({ search: previous => ({ ...previous, preview, page: undefined, auditPage: undefined, view: undefined }) })} />}</Field>
      {target && credential ? <Row>{renderIdentity?.(target, credential)}</Row> : open}
      {target && credential && !credential.bearer && <p>{t('connectB.platform.signInHelp')}</p>}
      {target && updatedAt && Date.parse(updatedAt) > Date.parse(target.created_at) && <Alert tone="warning">{t('connectB.platform.stale')}</Alert>}
    </Stack></Card>
    {target && credential?.bearer && <div key={target.id + ':' + credential.revision}>{children({
      target, token: credential.token, bearer: credential.bearer, key: scope + ':' + credential.revision,
    })}</div>}
  </Stack>
}
