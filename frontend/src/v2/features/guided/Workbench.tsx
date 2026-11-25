import { useQuery } from '@tanstack/react-query'
import { Link, useSearch } from '@tanstack/react-router'
import { Suspense } from 'react'
import { isLivePreview, isReady } from '../../../shell/ai/seeItLogic'
import { useT } from '../../i18n'
import { Alert, Button, DesktopOnlyCard, EmptyState, ErrorBoundary, Field, Row, Select, Skeleton, Stack } from '../../ui'
import { previewsOptions } from './api/delivery'
import { previewDeadline, previewJson, previewKeys, previewOptions, proxyAddress, usePreviewLifecycle } from './api/preview'
import type { Preview } from './api/delivery'
import type { Credential } from './state/preview'
import { usePreviewCredentials } from './components/PreviewCredentials'
import { ConfirmAction, DeliveryError } from './components/DeliveryControls'
import { RequestConsole, Scalar } from './components/PreviewTools'
import { usePreviewToolSearch } from './components/usePreviewToolSearch'

export default function Workbench({ project, write, verified }: { project: string; write: boolean; verified: boolean }) {
  const t = useT()
  const search = useSearch({ strict: false })
  const { credentials } = usePreviewCredentials()
  const previews = useQuery({ ...previewsOptions(project), enabled: verified })
  const updateSearch = usePreviewToolSearch()
  const lifecycle = usePreviewLifecycle(project)
  const running = previews.data?.filter(item => isLivePreview(item.state)) ?? []
  const current = running.find(item => item.id === search.preview)
    ?? running.find(item => credentials[item.id] && isReady(item.state))
    ?? running[0]
  const detail = useQuery({
    ...previewOptions(project, current?.id ?? ''), initialData: current, staleTime: 2000,
  })
  const preview = detail.data
  const credential = preview && credentials[preview.id]
  const starting = preview?.state === 'starting' && Date.now() - Date.parse(preview.created_at) < previewDeadline
  const setup = <Button asChild><Link to="/projects/$projectId/$section" params={{ projectId: project, section: 'see' }}
    search={preview ? { preview: preview.id, workspace: preview.workspace_id ?? undefined } : undefined}>{t('nav.see')}</Link></Button>
  if (!verified) return <EmptyState title={t('guided.verify')} action={<Button asChild><Link to="/account">{t('account.title')}</Link></Button>} />
  if (previews.isPending) return <Skeleton lines={5} label={t('preview.loading')} />
  if (previews.isError) return <Alert tone="danger" action={<Button onClick={() => void previews.refetch()}>{t('common.retry')}</Button>}>{t('preview.loadError')}</Alert>

  function select(id: string) { updateSearch({ preview: id, tool: undefined, role: undefined }) }
  return <Stack>
    {current && running.length > 1 && <Field label={t('shell.workbenchPreview')}>{attrs =>
      <Select triggerProps={attrs} value={current.id}
        options={running.map(item => ({ value: item.id, label: t('common.serverText', { text: item.id }) }))}
        onValueChange={select} />
    }</Field>}
    <DeliveryError error={lifecycle.error} reload={() => { lifecycle.reset(); void previews.refetch() }} />
    {detail.isError && <Alert tone="danger" action={<Button onClick={() => void detail.refetch()}>{t('common.retry')}</Button>}>{t('preview.loadError')}</Alert>}
    {starting || lifecycle.isPending ? <Skeleton lines={5} label={t('preview.starting')} />
      : preview && credential && isReady(preview.state)
        ? <WorkbenchTools key={preview.id + ':' + credential.revision} preview={preview} credential={credential} write={write} />
        : <EmptyState title={t('shell.workbenchEmpty')} action={<>
          {setup}
          {write && (preview && isReady(preview.state) ? <ConfirmAction label={t('preview.reconnect')}
            title={t('preview.rotate')} description={t('preview.rotateBody')} destructive={false} pending={lifecycle.isPending}
            onConfirm={() => lifecycle.mutateAsync({ type: 'rotate', id: preview.id }).then(result => select(result.id))} />
            : <Button variant="primary" onClick={() => lifecycle.mutate({ type: 'start', workspace: search.workspace }, {
              onSuccess: result => select(result.id),
            })}>{t('preview.start')}</Button>)}
        </>} />}
  </Stack>
}

function WorkbenchTools({ preview, credential, write }: { preview: Preview; credential: Credential; write: boolean }) {
  const t = useT()
  const search = useSearch({ strict: false })
  const updateSearch = usePreviewToolSearch()
  const reference = search.workbench === 'reference'
  const api = useQuery({
    queryKey: [...previewKeys.proxy(preview.id, credential.revision), 'openapi'],
    queryFn: async () => {
      const doc = await previewJson<Record<string, unknown>>(preview, credential, '/openapi.json')
      if (!doc || typeof doc.openapi !== 'string' || !doc.paths || typeof doc.paths !== 'object') throw new Error('preview_openapi')
      return doc
    },
    retry: false, gcTime: 0,
  })
  if (api.isPending) return <Skeleton lines={6} label={t('preview.loadingApi')} />
  if (api.isError) return <Alert tone="danger" action={<Button onClick={() => void api.refetch()}>{t('common.retry')}</Button>}>{t('preview.apiError')}</Alert>

  const relayError = (retry: () => void) => <Alert tone="danger" action={<Button onClick={retry}>{t('common.retry')}</Button>}>{t('preview.apiError')}</Alert>
  return <Stack>
    <Row role="group" aria-label={t('shell.workbench')}>
      <Button aria-pressed={!reference} onClick={() => updateSearch({ workbench: 'console' })}>{t('preview.console')}</Button>
      <Button aria-pressed={reference} onClick={() => updateSearch({ workbench: 'reference' })}>{t('preview.reference')}</Button>
    </Row>
    <ErrorBoundary key={String(reference)} fallback={relayError}>
      {reference ? <Suspense fallback={<Skeleton lines={8} label={t('preview.loadingApi')} />}>
        <Scalar document={api.data} origin={proxyAddress(preview, '/').href} />
      </Suspense> : <>
        <div className="v2-phone-only"><DesktopOnlyCard /></div>
        <div className="v2-phone-hidden"><RequestConsole preview={preview} credential={credential} doc={api.data} write={write} /></div>
      </>}
    </ErrorBoundary>
  </Stack>
}
