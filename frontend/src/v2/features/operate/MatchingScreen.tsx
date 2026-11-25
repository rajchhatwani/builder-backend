import { useRef, useState } from 'react'
import { useT } from '../../i18n'
import { ConfirmDestructive, Form } from '../../patterns'
import { Button, Grid, Row, Stack } from '../../ui'
import { noNullIssue } from '../../validators/operateRuntime'
import { MATCH_STATES, parseBatchRequests, parseCandidates } from '../../../shell/operations/opsLogic'
import { useRuntimeWrite } from './api/live'
import type { LiveProps, Page, Session } from './api/live'
import { canWrite } from './api/operate'
import { assignmentPath } from './api/tools'
import type { Assignment, AssignBody, BatchBody, BatchResult, RankBody, RankResult } from './api/tools'
import { useOperateDate, useOperateSearch } from './components/Common'
import { choices, Columns, data, Details, Empty, enumLabel, field, key, optional, Pager, Panel, Pick, Refresh, RuntimeState, serverFields, text, useRuntimeQuery, WriteStatus } from './components/Runtime'
import { PageSize, pointFields, PointGroup, readPoint, ToolsLinks, useListSize } from './components/RuntimeTools'
import { ToolScreen } from './components/ToolScreen'

const assignmentsPath = '/matching/assignments'

export default function MatchingScreen(props: LiveProps) {
  return <ToolScreen id={props} title={'matching'}>{session => <Matching session={session} writable={canWrite(props)} />}</ToolScreen>
}

function Matching({ session, writable }: { session: Session; writable: boolean }) {
  return <Stack gap={4}>
    <ToolsLinks session={session} sections={['matchingsettings', 'map']} />
    <Solve session={session} writable={writable} />
    <Assignments session={session} writable={writable} />
  </Stack>
}

function Solve({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const [mode, setMode] = useState('rank')
  const [offer, setOffer] = useState<AssignBody>()
  const [commit, setCommit] = useState<BatchBody>()
  const submit = useRef<HTMLButtonElement>(null)
  const rank = useRuntimeWrite<RankBody, RankResult>(session, '/matching/rank', 'POST', false)
  const assign = useRuntimeWrite<AssignBody, Assignment>(session, assignmentsPath)
  const batch = useRuntimeWrite<BatchBody, BatchResult>(session, '/matching/batch')
  const ranked = rank.data?.data
  const solved = batch.data?.data
  const assigning = mode === 'assign'
  const batching = mode.startsWith('batch')
  const active = batching ? batch : assigning ? assign : rank
  const modes = writable ? ['rank', 'assign', 'batchPreview', 'batchCommit'] : ['rank']
  const score = (row: { score: number; distance_m: number }) => [data(t, row.score), data(t, row.distance_m)]
  return <Panel title={'solveMatching'}>
    <Pick label={t(key('matchingOperation'))} value={mode} options={modes.map(value => ({ value, label: t(key(value)) }))} onChange={setMode} />
    <Form fields={[
      { ...field(t, 'candidates', { area: true, validate: value => {
        const parsed = parseCandidates(value)
        return parsed.ok ? undefined : { key: key('value'), values: { value: parsed.error } }
      } }), hint: t(key('candidateHelp')) },
      ...(batching ? [{ ...field(t, 'requests', { area: true, validate: value => {
        const parsed = parseBatchRequests(value)
        return parsed.ok ? undefined : { key: key('value'), values: { value: parsed.error } }
      } }), hint: t(key('requestsHelp')) }] : pointFields(t, 'request')),
      ...(assigning ? [field(t, 'request_ref', { label: 'requestRef', max: 128, required: true, validate: noNullIssue })] : []),
    ]} layout={controls => <Stack>{controls.candidates}{controls.request_ref}
      {batching ? controls.requests : <PointGroup label={'requestPoint'}><Grid>{controls.requestlat}{controls.requestlng}</Grid></PointGroup>}
    </Stack>} pending={active.isPending} submitLabel={t(key(mode))} submitProps={{ ref: submit }}
      serverErrors={serverFields(active.error, { 'point.lat_micro': 'requestlat', 'point.lng_micro': 'requestlng' },
        path => path.startsWith('candidates.') ? 'candidates' : path.startsWith('requests.') ? 'requests' : undefined)}
      onSubmit={form => {
        const parsed = parseCandidates(text(form, 'candidates'))
        if (!parsed.ok) return
        const candidates = parsed.items
        if (batching) {
          const requests = parseBatchRequests(text(form, 'requests'))
          if (!requests.ok) return
          const body = { candidates, requests: requests.items, commit: mode === 'batchCommit' }
          if (body.commit) setCommit(body)
          else batch.mutate(body)
        } else {
          const point = readPoint(form, 'request')
          if (assigning) setOffer({ candidates, point, request_ref: text(form, 'request_ref') })
          else rank.mutate({ candidates, point })
        }
      }} />
    {offer && <ConfirmDestructive open onOpenChange={open => { if (!open) setOffer(undefined) }} returnFocus={submit}
      title={t(key('assign'))} description={t(key('assignHelp'), { request: offer.request_ref })} action={t(key('confirmAssign'))}
      pending={assign.isPending} onConfirm={async () => {
        await assign.mutateAsync(offer)
      }} error={assign.isError ? t(key('assignFailed')) : undefined} />}
    {commit && <ConfirmDestructive open onOpenChange={open => { if (!open) setCommit(undefined) }} returnFocus={submit}
      title={t(key('batchCommit'))} description={t(key('batchHelp'))} action={t(key('confirmBatch'))}
      pending={batch.isPending} onConfirm={async () => {
        await batch.mutateAsync(commit)
      }} error={batch.isError ? t(key('assignFailed')) : undefined} />}
    <WriteStatus error={active.error} reload={active.reset} success={assigning && assign.data ?
      t(key('offerCreated'), { candidate: assign.data.data.candidate_id }) : batching && solved ? t(key(batch.variables?.commit ? 'batchSaved' : 'batchSolved')) : undefined} />
    {!assigning && !batching && ranked && <Stack>
      {ranked.items.length ? <Columns label={'rankedCandidates'} names={['candidate', 'score', 'distanceM', 'distancePart', 'loadPart', 'ratingPart']}
        rows={ranked.items.map(row => ({ id: row.candidate_id, cells: [data(t, row.candidate_id), ...score(row),
          data(t, row.parts.distance), data(t, row.parts.load), data(t, row.parts.rating)] }))} /> : <p>{t(key('noCandidates'))}</p>}
      {ranked.excluded.length > 0 && <Columns label={'excludedCandidates'} names={['candidate', 'reason']} rows={ranked.excluded.map(row => ({
        id: row.candidate_id, cells: [data(t, row.candidate_id), enumLabel(t, row.reason)],
      }))} />}
    </Stack>}
    {batching && solved && <Stack>
      <Details values={[
        ['solver', data(t, solved.solver)], ['totalScore', data(t, solved.total_score)], ['createdOffers', data(t, solved.assignments.length)],
        ['unassigned', data(t, solved.unassigned.join(', '))], ['skippedRequests', data(t, solved.skipped.join(', '))],
      ]} />
      {solved.pairs.length > 0 && <Columns label={'solvedPairs'} names={['requestRef', 'candidate', 'score', 'distanceM']} rows={solved.pairs.map(row => ({
        id: row.request_ref, cells: [data(t, row.request_ref), data(t, row.candidate_id), ...score(row)],
      }))} />}
    </Stack>}
  </Panel>
}

function Assignments({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const { size, pickSize } = useListSize(100)
  const page = search.page ?? 1
  const list = useRuntimeQuery<Page<Assignment>>(session, assignmentsPath, { limit: size, offset: (page - 1) * size,
    status: search.status, request_ref: search.request, candidate_id: search.candidate })
  const detail = useRuntimeQuery<Assignment>(session, assignmentPath(search.edit ?? ''), {}, !!search.edit)
  return <Stack>
    <Panel title={'assignments'}>
      <Form key={JSON.stringify([search.request, search.candidate])} fields={[
        field(t, 'request', { label: 'requestRef', value: search.request, max: 128, validate: noNullIssue }),
        field(t, 'candidate', { value: search.candidate, max: 128, validate: noNullIssue }),
      ]} submitLabel={t(key('apply'))} onSubmit={form => change({ request: optional(form, 'request'), candidate: optional(form, 'candidate'), page: undefined })} />
      <Row><Pick label={t(key('status'))} value={search.status ?? ''} options={choices(t, MATCH_STATES)}
        onChange={status => change({ status: status || undefined, page: undefined })} />
        <PageSize value={size} onChange={pickSize} /><Refresh run={list.refetch} />
        {writable && <OfferAction session={session} verb="expireDue" />}</Row>
      {list.isPending || list.isError ? <RuntimeState error={list.error} retry={list.refetch} /> :
        list.data.items.length ? <Columns label={'assignments'} names={['requestRef', 'candidate', 'status', 'score', 'distanceM', 'expires', 'actions']}
          rows={list.data.items.map(row => ({
            id: row.id, cells: [<Button aria-expanded={search.edit === row.id} onClick={() => change({ edit: search.edit === row.id ? undefined : row.id })}>{data(t, row.request_ref)}</Button>,
              data(t, row.candidate_id), enumLabel(t, row.status), data(t, row.score), data(t, row.distance_m), date(row.expires_at),
              writable && row.status === 'offered' ? <Row>{(['accept', 'reject', 'expire'] as const).map(verb => <OfferAction key={verb} session={session} verb={verb} row={row} />)}</Row> : null],
          }))} /> : <Empty message="noAssignments" onAction={list.refetch} />}
      <Pager label={'assignments'} page={page} size={size} total={list.data?.total ?? 0} change={page => change({ page })} />
    </Panel>
    {search.edit && <Panel title={'assignmentDetail'}>
      {detail.isPending || detail.isError ? <RuntimeState error={detail.error} retry={detail.refetch} /> :
        <Details values={[
          ['requestRef', data(t, detail.data.request_ref)], ['candidate', data(t, detail.data.candidate_id)], ['status', enumLabel(t, detail.data.status)],
          ['offeredAt', date(detail.data.offered_at)], ['expires', date(detail.data.expires_at)], ['decidedAt', date(detail.data.decided_at)],
          ['decidedBy', data(t, detail.data.decided_by)],
          ['score', data(t, detail.data.score)], ['distanceM', data(t, detail.data.distance_m)],
        ]} />}
    </Panel>}
  </Stack>
}

function OfferAction({ session, verb, row }: { session: Session; verb: 'accept' | 'reject' | 'expire' | 'expireDue'; row?: Assignment }) {
  const t = useT()
  const write = useRuntimeWrite<undefined, Assignment | { expired: number }>(session, row && verb !== 'expireDue' ?
    `${assignmentPath(row.id)}/${verb}` : '/matching/expire-due')
  const action = t(key(verb))
  return <Stack>
    {verb === 'accept' ? <Button disabled={write.isPending} onClick={() => write.mutate(undefined)}>{action}</Button> :
      <ConfirmDestructive trigger={<Button variant="danger">{action}</Button>} title={action} description={t(key(verb + 'Help'), { request: row?.request_ref ?? '' })}
        action={action} pending={write.isPending} onConfirm={async () => { await write.mutateAsync(undefined) }} />}
    <WriteStatus error={write.error} reload={write.reset} success={write.data && 'expired' in write.data.data ?
      t(key('expiredOffers'), { count: write.data.data.expired }) : undefined} />
  </Stack>
}
