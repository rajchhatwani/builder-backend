import { useQuery } from '@tanstack/react-query'
import { useT } from '../../i18n'
import { Form, ReadOnlyNote } from '../../patterns'
import { Alert, Badge, Button, EmptyState, Input, Progress, Row, Stack } from '../../ui'
import { noNullIssue, uuidIssue } from '../../validators/operateRuntime'
import { evalHistoryOptions, evalRunOptions, suitesOptions, useAiAccess, useRunEval } from './api/ai'
import type { EvalRun } from './api/ai'
import type { LiveProps, Session } from './api/live'
import { canWrite } from './api/operate'
import { AiActions, AiFeedback, AiPermission, AiRuntime, useAiFormat } from './components/AiRuntime'
import { SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { Columns, data, Empty, key, optional, Pager, Panel } from './components/Runtime'

export default function EvalsScreen(props: LiveProps) {
  return <AiRuntime id={props} title={'evals'}>{session => <Evals session={session} writable={canWrite(props)} />}</AiRuntime>
}

function Evals({ session, writable }: { session: Session; writable: boolean }) {
  const t = useT()
  const format = useAiFormat()
  const date = useOperateDate()
  const { search, change } = useOperateSearch()
  const suites = useQuery(suitesOptions(session))
  const size = 20
  const page = search.page ?? 1
  const runs = useQuery(evalHistoryOptions(session, { limit: size, offset: (page - 1) * size, suite: search.suite }))
  const selected = search.run && !uuidIssue(search.run) ? search.run : undefined
  const request = useRunEval(session)
  const fresh = request.data?.data.id === selected ? request.data?.data : undefined
  const detail = useQuery(evalRunOptions(session, fresh ? undefined : selected))
  const access = useAiAccess(session, writable)
  const open = (id: string) => change({ run: id })
  const clear = () => change({ suite: undefined, page: undefined })
  return <Stack gap={4}>
    <AiActions id={session.projectId} settings="evalssettings" testId="evals-refresh" refresh={() => Promise.all([
      suites.refetch(), runs.refetch(), access.retry(), ...(selected && !fresh ? [detail.refetch()] : []),
    ])} />
    <Alert><span data-testid="evals-dry-note">{t(key('evalDryNote'))}</span></Alert>
    <Panel title={'evalSuites'}>
      <AiPermission access={access}>{writable && !access.eval && <ReadOnlyNote>{t(key('evalReadOnly'))}</ReadOnlyNote>}</AiPermission>
      <AiFeedback error={request.error} retry={request.reset} write />
      {suites.isPending || suites.isError ? <AiFeedback error={suites.error} retry={suites.refetch} /> :
        suites.data.length ? <Columns label={'evalSuites'} names={['suite', 'agent', 'cases', 'passMark', 'lastRun', 'run']}
          rows={suites.data.map(suite => ({ id: suite.name, testId: 'suite-row', cells: [
            data(t, suite.name), data(t, suite.agent), format.count(suite.case_count), format.bp(suite.pass_bp),
            suite.latest ? <Stack gap={1}><Button onClick={() => open(suite.latest!.id)}
              aria-label={t(key('openLatest'), { suite: suite.name })}>
              {t(key('verdictScore'), { verdict: t(key(suite.latest.passed ? 'passed' : 'failed')), score: format.bp(suite.latest.score_bp) })}
            </Button>{date(suite.latest.created_at)}</Stack> : t(key('neverRun')),
            access.eval ? <Button variant="primary" data-testid="suite-run" disabled={request.isPending}
              onClick={() => request.mutate(suite.name, { onSuccess: result => change({ run: result.data.id, page: undefined }) })}
              aria-label={t(key(request.isPending && request.variables === suite.name ? 'runningNamedSuite' : 'runNamedSuite'), { suite: suite.name })}>
              {t(key(request.isPending && request.variables === suite.name ? 'runningSuite' : 'runDry'))}
            </Button> : data(t, null),
          ] }))} /> : <EmptyState title={t(key('noSuites'))} action={<SectionLink id={session.projectId} section="evalssettings" label={t(key('evalssettings'))} />} />}
    </Panel>
    {selected && <Panel title={fresh ? 'freshEval' : 'evalResult'}>
      <Row><Button onClick={() => change({ run: undefined })}>{t(key('close'))}</Button></Row>
      {fresh || detail.data ? <EvalDetail run={fresh ?? detail.data!} /> : <AiFeedback error={detail.error} retry={detail.refetch} />}
      {detail.data && detail.isError && <AiFeedback error={detail.error} retry={detail.refetch} />}
    </Panel>}
    <Panel title={'runHistory'}>
      <Form key={search.suite} fields={[{ name: 'suite', label: t(key('suiteName')), hint: t(key('exactSuite')), validateWith: noNullIssue,
        control: attrs => <Input {...attrs} defaultValue={search.suite} maxLength={40} data-testid="runs-suite" /> }]}
        submitLabel={t(key('apply'))} onSubmit={form => change({ suite: optional(form, 'suite'), page: undefined })}
        actions={search.suite && <Button onClick={clear}>{t(key('clearFilter'))}</Button>} />
      {runs.isPending || runs.isError ? <AiFeedback error={runs.error} retry={runs.refetch} /> :
        runs.data.items.length ? <Columns label={'evalHistory'} names={['created', 'suite', 'score', 'verdict', 'casesPassed', 'startedBy', 'evalResult']}
          rows={runs.data.items.map(run => ({ id: run.id, testId: 'run-row', cells: [
            date(run.created_at), data(t, run.suite), format.bp(run.score_bp),
            <Badge tone={run.passed ? 'success' : 'danger'}>{t(key(run.passed ? 'passed' : 'failed'))}</Badge>,
            format.pair(run.passed_count, run.total), data(t, run.created_by),
            <Button data-testid="run-open" aria-label={t(key('showRun'), { name: run.suite, when: date(run.created_at) })}
              onClick={() => open(run.id)}>{t(key('show'))}</Button>,
          ] }))} /> : <Empty message={search.suite ? 'noFilteredEvals' : 'noEvalRuns'}
          action={search.suite ? 'clearFilter' : 'refresh'} onAction={search.suite ? clear : runs.refetch} />}
      <Pager label={'evalHistory'} page={page} total={runs.data?.total ?? 0} size={size} change={page => change({ page })} />
    </Panel>
  </Stack>
}

function EvalDetail({ run }: { run: EvalRun }) {
  const t = useT()
  const format = useAiFormat()
  const date = useOperateDate()
  return <Stack data-testid="eval-detail">
    <Row><span data-testid="eval-verdict"><Badge tone={run.passed ? 'success' : 'danger'}>{t(key(run.passed ? 'suitePassed' : 'suiteFailed'))}</Badge></span>
      <strong>{format.bp(run.score_bp)}</strong>
      <span>{t(key('passedCount'), { passed: format.count(run.passed_count), total: format.count(run.total) })}</span>
    </Row>
    <Row><span>{t(key('suiteAgent'), { suite: run.suite, agent: run.agent })}</span><span>{date(run.created_at)}</span></Row>
    <Progress value={run.score_bp} max={10000} data-testid="eval-progress" label={t(key('suiteScore'))} />
    <p>{t(key('evalDryResult'))}</p>
    <Columns label={'caseResults'} names={['evalCaseName', 'result', 'proposedActions', 'checks']} rows={run.results.map(result => ({
      id: result.case, testId: 'eval-case', cells: [
        data(t, result.case), <Badge tone={result.passed ? 'success' : 'danger'}>{t(key(result.passed ? 'pass' : 'fail'))}</Badge>,
        data(t, result.proposed.join(', ')), result.error_code ? t(key('caseError'), { code: result.error_code }) :
          t(key(result.passed ? 'casePassed' : 'caseFailed')),
      ],
    }))} />
  </Stack>
}
