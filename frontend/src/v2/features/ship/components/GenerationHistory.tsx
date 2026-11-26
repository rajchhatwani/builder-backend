import { useQuery } from '@tanstack/react-query'
import { useT } from '../../../i18n'
import { SettingsSection } from '../../../patterns'
import { Button, CodeBlock, Disclosure, EmptyState, Grid, Pagination, Row, Stack, Table } from '../../../ui'
import { generationOptions, generationsOptions, pageSize } from '../api/ship'
import { ShipLoading, ShipProblem, useShipFormat, useShipSearch } from './Common'

export function GenerationHistory({ id, busy, onDownload }: { id: string; busy: boolean; onDownload: () => void }) {
  const t = useT()
  const { search, change } = useShipSearch()
  const page = search.page ?? 1
  const history = useQuery(generationsOptions(id, page))
  const { columns, date, bytes } = useShipFormat()
  return <Stack>
    <SettingsSection title={t('ship.history')}>
      {history.isPending ? <ShipLoading label={t('ship.historyLoading')} /> :
        history.isError ? <ShipProblem error={history.error} message={t('ship.historyError')} retry={history.refetch} /> :
          <>
            {history.data.items.length ? <Table label={t('ship.history')} columns={columns('when', 'hash', 'files', 'size')}
              rows={history.data.items.map(item => ({
                id: item.id, cells: [
                  <Button onClick={() => void change({ generation: item.id })}
                    aria-label={t('ship.viewGeneration', { date: date(item.created_at), hash: item.spec_hash.slice(0, 12) })}>{date(item.created_at)}</Button>,
                  <code>{t('ship.value', { value: item.spec_hash.slice(0, 12) })}</code>,
                  t('ship.value', { value: item.file_count }), bytes(item.total_size),
                ],
              }))} /> : <EmptyState title={t(page === 1 ? 'ship.historyEmpty' : 'ship.pageEmpty')}
                action={page === 1 ? <Button disabled={busy} variant="primary" onClick={onDownload}>{t('ship.zip')}</Button> :
                  <Button onClick={() => void change({ page: undefined })}>{t('ship.firstPage')}</Button>} />}
            {(page > 1 || history.data.total > pageSize) && <Pagination label={t('ship.history')} page={page}
              pages={Math.ceil(history.data.total / pageSize)} onChange={value => void change({ page: value > 1 ? value : undefined, generation: undefined })} />}
          </>}
    </SettingsSection>
    {search.generation && <GenerationDetail id={id} generation={search.generation} close={() => void change({ generation: undefined })} />}
  </Stack>
}

function GenerationDetail({ id, generation, close }: { id: string; generation: string; close: () => void }) {
  const t = useT()
  const query = useQuery(generationOptions(id, generation))
  const { columns, date, bytes } = useShipFormat()
  const detail = query.data
  return <SettingsSection title={t('ship.generationDetail')}>
    <Row><Button onClick={close}>{t('common.close')}</Button></Row>
    {query.isPending ? <ShipLoading label={t('ship.generationLoading')} /> :
      query.isError ? <ShipProblem error={query.error} message={t('ship.generationDetailError')} retry={query.refetch} /> :
        detail && <>
          <Grid role="list">{[['generationId', detail.id], ['hash', detail.spec_hash], ['when', date(detail.created_at)]]
            .map(([label, value]) => <Stack key={label} gap={1} role="listitem">
              <span className="v2-muted">{t('ship.' + label)}</span><code>{t('ship.value', { value })}</code>
            </Stack>)}</Grid>
          <Disclosure label={t('ship.snapshot')}><CodeBlock code={JSON.stringify(detail.spec_snapshot, null, 2)} /></Disclosure>
          <Disclosure label={t('ship.manifest')} open><Table label={t('ship.manifest')} columns={columns('path', 'size', 'sha')}
            rows={detail.file_manifest.map(file => ({ id: file.path, cells: [
              <code>{t('ship.value', { value: file.path })}</code>, bytes(file.size), <code>{t('ship.value', { value: file.sha256 })}</code>,
            ] }))} /></Disclosure>
        </>}
  </SettingsSection>
}
