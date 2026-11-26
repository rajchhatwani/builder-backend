import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Checkbox, EmptyState, Grid, Pagination, Row, Stack } from '../../ui'
import { buildError, buildQueries, useBuildWrite, versionPageSize, writeTimeline } from './api/build'
import type { TimelineAction } from './api/build'
import { BuildFailure, BuildLoad, BuildPage, Pick, SectionLink, useBuildDate, useVersionLabel, WeakeningDetails, WriteAccess } from './components/shared'
import type { BuildScreenProps } from './components/shared'
import { route, useBuildRoute } from './routes'

const actors = ['all', 'user', 'agent', 'mcp', 'system']
export default function TimelineScreen({ access }: BuildScreenProps) {
  const { projectId } = useBuildRoute()
  return <BuildPage screen="timeline"><Timeline key={projectId} access={access} /></BuildPage>
}

function Timeline({ access }: BuildScreenProps) {
  const t = useT()
  const label = useVersionLabel()
  const date = useBuildDate()
  const { projectId, search, update } = useBuildRoute()
  const page = search.page ?? 1
  const current = useQuery(buildQueries.ops(projectId, 1))
  const versions = useQuery(buildQueries.ops(projectId, page))
  const write = useBuildWrite(projectId, writeTimeline)
  const [weakening, setWeakening] = useState<TimelineAction>()
  const [showWeakening, setShowWeakening] = useState(false)
  const latest = current.data?.items[0]?.seq ?? 0
  const selected = search.version
  const reverted = selected === undefined ? [] : (current.data?.items ?? []).filter(op => op.seq > selected)
  const count = selected === undefined ? 0 : Math.max(0, latest - selected)
  const disabled = !access.writable || write.isPending
  const filter = actors.includes(search.kind ?? '') ? search.kind! : 'all'
  const filtered = versions.data?.items.filter(op => filter === 'all' || filter === op.actor.kind) ?? []
  const reload = () => {
    setWeakening(undefined)
    setShowWeakening(false)
    write.reset()
    void current.refetch()
    void versions.refetch()
  }

  async function apply(action: TimelineAction) {
    try {
      const op = await write.mutateAsync({ ...action, head: action.head ?? latest })
      setWeakening(undefined)
      update({ version: op.seq, page: undefined })
    } catch (error) {
      if (!action.confirm && buildError(error)?.code === 'access_weakened') {
        setWeakening({ ...action, head: action.head ?? latest })
        return
      }
      throw error
    }
  }

  const danger = (action: TimelineAction, text: string, detail: string, blocked = disabled) =>
    <ConfirmDestructive title={text} description={detail} action={text} trigger={<Button variant="danger" disabled={blocked}>{text}</Button>}
      onConfirm={() => apply(action)} error={write.isError && buildError(write.error)?.code !== 'access_weakened' ? t('common.actionFailed') : undefined} />

  return <BuildLoad reads={[current, versions]}>
    <WriteAccess access={access} />
    <BuildFailure error={write.error} reload={reload} onWeakening={weakening && <Button variant="danger" onClick={() => setShowWeakening(true)}>{t('buildSpec.reviewAccess')}</Button>} />
    <ConfirmDestructive open={showWeakening} onOpenChange={setShowWeakening}
      title={t('buildSpec.weakeningTitle')} description={t('buildSpec.weakening')} action={t('buildSpec.confirmAccess')}
      onConfirm={() => weakening ? apply({ ...weakening, confirm: true }) : undefined} />
    {weakening && <WeakeningDetails error={write.error} />}
    {write.isSuccess && <Alert tone="success">{t('buildSpec.timeline.applied')}</Alert>}
    {!latest ? <EmptyState title={t('buildSpec.timeline.empty')} description={t('buildSpec.timeline.emptyDetail')}
      action={<SectionLink projectId={projectId} section="model">{t('buildSpec.openModel')}</SectionLink>} /> : <>
      <Row>
        {danger({ kind: 'undo' }, t('buildSpec.timeline.undo'), t('buildSpec.timeline.undoDetail'))}
        {danger({ kind: 'redo' }, t('buildSpec.timeline.redo'), t('buildSpec.timeline.redoDetail'))}
      </Row>
      <Row>
        <Pick label={t('buildSpec.timeline.actor')} value={filter} options={actors.map(value => ({ value, label: t('buildSpec.actors.' + value) }))}
          onChange={kind => update({ kind: kind === 'all' ? undefined : kind, page: undefined })} />
        <Checkbox label={t('buildSpec.timeline.technical')} checked={Boolean(search.technical)} onChange={event => update({ technical: event.target.checked || undefined })} />
      </Row>
      <Grid gap={4}>
        <SettingsSection title={t('buildSpec.timeline.versions')}>
          {!filtered.length && <p className="v2-muted">{t('buildSpec.timeline.noActor')}</p>}
          {filtered.map(op => <Stack key={op.seq} gap={1}>
            <Row><Button variant="ghost" aria-pressed={selected === op.seq} onClick={() => update({ version: op.seq })}>{label(op)}</Button>
              {op.seq === latest && <Badge tone="success">{t('buildSpec.timeline.current')}</Badge>}</Row>
            <p className="v2-muted">{t('buildSpec.timeline.byline', {
              actor: op.actor.email ?? t('buildSpec.actors.' + (actors.includes(op.actor.kind) ? op.actor.kind : 'other')),
              when: date(op.created_at),
            })}</p>
            {search.technical && <code>{t('buildSpec.timeline.opDetail', { type: op.op_type, origin: op.origin, before: op.spec_hash_before, after: op.spec_hash_after, ref: op.ref_seq ?? t('buildSpec.none') })}</code>}
          </Stack>)}
          <Row><Button aria-pressed={selected === 0} onClick={() => update({ version: 0 })}>{t('buildSpec.timeline.start')}</Button></Row>
          <Pagination label={t('buildSpec.timeline.versions')} page={page} pages={Math.ceil((versions.data?.total ?? 0) / versionPageSize)}
            onChange={page => update({ page: page > 1 ? page : undefined })} />
        </SettingsSection>
        <SettingsSection title={t('buildSpec.timeline.preview')}>
          {selected === undefined ? <p>{t('buildSpec.timeline.pick')}</p> : <>
            <p>{selected === 0 ? t('buildSpec.timeline.start') : t('buildSpec.versionNumber', { version: selected })}</p>
            <p>{t('buildSpec.timeline.impact', { count })}</p>
            {reverted.length > 0 && <ul>{reverted.map(op => <li key={op.seq}>{label(op)}</li>)}</ul>}
            {count > reverted.length && <p>{t('buildSpec.timeline.more', { count: count - reverted.length })}</p>}
            <Row>
              <Button asChild><Link to={route} params={{ projectId, section: 'specdiff' }} search={{ base: selected }}>{t('buildSpec.timeline.compare')}</Link></Button>
              {danger({ kind: 'restore', seq: selected }, t('buildSpec.timeline.restore'), t('buildSpec.timeline.restoreDetail'), disabled || !count)}
            </Row>
          </>}
        </SettingsSection>
      </Grid>
    </>}
  </BuildLoad>
}
