import { useState } from 'react'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import { Button, Disclosure, Stack } from '../../../ui'
import { jsonObjectIssue, readJsonObject, uuidIssue } from '../../../validators/operateRuntime'
import { useRuntimePdf } from '../api/live'
import type { LiveProps, Session } from '../api/live'
import { useOperateSearch } from './Common'
import { data, Empty, field, key, Pick, Refresh, RuntimeContents, RuntimeState, text, useRuntimeQuery, WriteStatus } from './Runtime'
import { usePdfUrl } from './usePdfUrl'

type GeneratedTemplate = { id: string; title: string; kind: string; entity: string | null }
export function GeneratedPdfs(props: LiveProps) {
  const t = useT()
  const [open, setOpen] = useState(false)
  return <Disclosure label={t(key('generatedPdfs'))} onToggle={event => setOpen(event.currentTarget.open)}>
    {open && <RuntimeContents id={props}>{session => <GeneratedList session={session} />}</RuntimeContents>}
  </Disclosure>
}

function GeneratedList({ session }: { session: Session }) {
  const t = useT()
  const { search, change } = useOperateSearch()
  const query = useRuntimeQuery<GeneratedTemplate[]>(session, '/documents')
  if (query.isPending || query.isError) return <RuntimeState error={query.error} retry={query.refetch} />
  if (!query.data.length) return <Empty message="noGeneratedPdfs" onAction={query.refetch} />
  const selected = query.data.find(item => item.id === search.view) ?? query.data[0]
  return <Stack>
    <Refresh run={query.refetch} />
    <Pick label={t(key('template'))} options={query.data.map(item => ({ value: item.id, label: data(t, item.title) }))}
      value={selected.id} onChange={view => change({ view })} />
    <RenderGenerated key={selected.id} session={session} item={selected} />
  </Stack>
}

function RenderGenerated({ session, item }: { session: Session; item: GeneratedTemplate }) {
  const t = useT()
  const render = useRuntimePdf(session, item.id, Boolean(item.entity))
  const url = usePdfUrl(render.data)
  return <Stack>
    <Form fields={item.entity ? [field(t, 'recordId', { max: 36, validate: uuidIssue })] :
      [field(t, 'sampleData', { area: true, value: '{}', validate: jsonObjectIssue })]}
      pending={render.isPending} submitLabel={t(key('renderGenerated'))} onSubmit={form =>
        render.mutate(item.entity ? { record: text(form, 'recordId') } : { data: readJsonObject(text(form, 'sampleData')) })} />
    <WriteStatus error={render.error} reload={render.reset} />
    {url && <Button asChild><a href={url} download={item.id + '.pdf'}>{t(key('downloadPdf'))}</a></Button>}
  </Stack>
}
