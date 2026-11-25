import { useEffect, useReducer, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { EXAMPLE_TRACE, linksOf, MAX_TRACE_BYTES, parseTrace } from '../../../shell/traces/traceLogic'
import type { ParsedTrace, WaterfallRow } from '../../../shell/traces/traceLogic'
import { useT } from '../../i18n'
import { SettingsSection } from '../../patterns'
import { Alert, Badge, Button, Disclosure, EmptyState, Field, Grid, Input, Pagination, RangeTrack, Row, Stack, Textarea } from '../../ui'
import type { OperateProps } from './api/operate'
import { LoadState, OperateScreen, SectionLink, useOperateDate, useOperateSearch } from './components/Common'
import { initialTrace, traceReducer } from './state/trace'
import './operate.css'

const pageSize = 50

export default function TracesScreen({ projectId }: OperateProps) {
  return <OperateScreen title={'operate.trace.title'} lead="operate.trace.lead"><Traces id={projectId} /></OperateScreen>
}

function Traces({ id }: { id: string }) {
  const t = useT()
  const { change } = useOperateSearch()
  const [state, dispatch] = useReducer(traceReducer, initialTrace)
  const fileRead = useRef(0)
  useEffect(() => () => { ++fileRead.current }, [])
  function load(draft: string) {
    const result = parseTrace(draft)
    change({ span: undefined, page: undefined }, true)
    dispatch(result.ok ? { type: 'loaded', draft, trace: result.trace } : { type: 'failed', draft, error: result.error })
  }
  async function upload(file: File) {
    const read = ++fileRead.current
    if (file.size > MAX_TRACE_BYTES) {
      dispatch({ type: 'failed', error: t('operate.trace.size') })
      return
    }
    dispatch({ type: 'file' })
    try {
      const contents = await file.text()
      if (read === fileRead.current) load(contents)
    } catch {
      if (read === fileRead.current) dispatch({ type: 'failed', error: t('operate.trace.fileError') })
    }
  }
  const show = () => load(state.draft)
  return <Stack gap={4}>
    <SettingsSection title={t('operate.trace.load')}>
      <Field id="operate-trace-document" label={t('operate.trace.document')} hint={t('operate.trace.format')}>{attrs => <Textarea {...attrs} rows={6}
        value={state.draft} disabled={state.reading} onChange={event => dispatch({ type: 'edit', draft: event.target.value })} />}</Field>
      <Row><Button variant="primary" onClick={show} disabled={state.reading || !state.draft.trim()}>{t('operate.trace.show')}</Button>
        <Button onClick={() => load(JSON.stringify(EXAMPLE_TRACE, null, 2))} disabled={state.reading}>{t('operate.trace.example')}</Button>
        <Button disabled={!state.draft && !state.trace && !state.error && !state.reading} onClick={() => {
          ++fileRead.current
          change({ span: undefined, page: undefined }, true)
          dispatch({ type: 'clear' })
        }}>{t('operate.trace.clear')}</Button></Row>
      <Field label={t('operate.trace.upload')}>{attrs => <Input {...attrs} type="file" accept="application/json,.json" disabled={state.reading}
        onChange={event => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (file) void upload(file)
        }} />}</Field>
      <Row><SectionLink id={id} section="observability" label={t('operate.obs.title')} /></Row>
      <Disclosure label={t('operate.trace.settings')}><p>{t('operate.trace.settingsHelp')}</p></Disclosure>
    </SettingsSection>
    {state.reading ? <LoadState retry={show} /> : state.error ?
      <Alert tone="danger" action={<Button disabled={!state.draft.trim()} onClick={show}>{t('common.retry')}</Button>}>
        <strong>{t('operate.trace.error')}</strong> {t('operate.data', { value: state.error })}
      </Alert> : state.trace ? <Waterfall trace={state.trace} id={id} /> :
      <EmptyState title={t('operate.trace.empty')} description={t('operate.trace.emptyHelp')}
        action={<Button onClick={() => document.getElementById('operate-trace-document')?.focus()}>{t('operate.trace.document')}</Button>} />}
  </Stack>
}

function useDuration() {
  const t = useT()
  return (ms: number) => Number.isFinite(ms) ? t(ms >= 1000 ? 'operate.trace.sec' : 'operate.trace.ms', {
    value: ms >= 1000 ? Number((ms / 1000).toFixed(ms >= 10_000 ? 1 : 2)) : Number(ms.toFixed(1)),
  }) : t('operate.emptyValue')
}

function Waterfall({ trace, id }: { trace: ParsedTrace; id: string }) {
  const t = useT()
  const duration = useDuration()
  const { search, change } = useOperateSearch()
  const refs = useRef(new Map<number, HTMLButtonElement>())
  const pages = Math.ceil(trace.rows.length / pageSize)
  const page = Math.min(search.page ?? 1, pages)
  const start = (page - 1) * pageSize
  const picked = Number(search.span ?? start)
  const index = Number.isInteger(picked) && picked >= 0 && picked < trace.rows.length ? picked : start
  const select = (span: number) => change({ span: String(span), page: Math.floor(span / pageSize) + 1 })
  function arrow(event: KeyboardEvent<HTMLButtonElement>, position: number) {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const next = Math.min(trace.rows.length - 1, Math.max(0, position + (event.key === 'ArrowDown' ? 1 : -1)))
    select(next)
    requestAnimationFrame(() => refs.current.get(next)?.focus())
  }
  const row = trace.rows[index]
  return <Stack gap={4}>
    {trace.warnings.length > 0 && <SettingsSection title={t('operate.trace.adjusted')}>
      <ul>{trace.warnings.slice(0, 20).map((warning, index) => <li key={index}>{t('operate.data', { value: warning })}</li>)}</ul>
      {trace.warnings.length > 20 && <p>{t('operate.trace.more', { count: trace.warnings.length - 20 })}</p>}
    </SettingsSection>}
    <SettingsSection title={t('operate.trace.waterfall')} description={t('operate.trace.summary', {
      id: trace.traceId, count: trace.rows.length, duration: duration(trace.totalMs),
    })}>
      <ul className="v2-trace-rows">{trace.rows.slice(start, start + pageSize).map(({ span, depth, widthPct, offsetPct, durationMs, onCriticalPath }, offset) => {
        const position = start + offset
        const error = span.status === 'error'
        return <li key={span.span_id}>
          <Button className="v2-trace-span" data-depth={Math.min(depth, 5)} aria-pressed={position === index}
            ref={button => { if (button) refs.current.set(position, button); else refs.current.delete(position) }}
            onClick={() => select(position)} onKeyDown={event => arrow(event, position)}>
            <Stack gap={1}><Row className="v2-spread">
              <strong>{t('operate.trace.row', { name: span.name, duration: duration(durationMs) })}</strong>
              <Row gap={1}>
                {error && <Badge tone="danger">{t('operate.trace.errorStatus')}</Badge>}
                {onCriticalPath && <Badge>{t('operate.trace.critical')}</Badge>}
              </Row>
            </Row>
            <RangeTrack offset={offsetPct} width={widthPct} variant={error ? 'warning' : onCriticalPath ? 'active' : 'default'} /></Stack>
          </Button>
        </li>
      })}</ul>
      {pages > 1 && <Pagination label={t('operate.trace.page')} page={page} pages={pages}
        onChange={next => select((next - 1) * pageSize)} />}
    </SettingsSection>
    <SpanDetails row={row} id={id} />
    <SettingsSection title={t('operate.trace.overview')}>
      <Grid><p>{t('operate.trace.errorCount', { count: trace.rows.filter(item => item.span.status === 'error').length })}</p>
        <p>{t('operate.trace.serviceCount', { count: new Set(trace.rows.map(item => item.span.service).filter(Boolean)).size })}</p></Grid>
    </SettingsSection>
  </Stack>
}

function SpanDetails({ row, id }: { row: WaterfallRow; id: string }) {
  const t = useT()
  const date = useOperateDate()
  const duration = useDuration()
  const { span } = row
  const entries = {
    service: span.service || t('operate.emptyValue'), status: t(span.status === 'error' ? 'operate.trace.errorStatus' : 'operate.trace.okStatus'),
    start: date(span.start_unix_ms), duration: duration(row.durationMs), id: span.span_id, children: row.childCount,
  }
  return <SettingsSection title={t('operate.trace.details')} description={t('operate.data', { value: span.name })}>
    <dl className="v2-operate-kv">{Object.entries(entries).map(([key, value]) =>
      <div key={key}><dt>{t('operate.trace.' + key)}</dt><dd>{t('operate.data', { value })}</dd></div>)}</dl>
    {Object.keys(span.attributes).length > 0 && <Stack><h3>{t('operate.trace.attributes')}</h3>
      <dl className="v2-operate-kv">{Object.entries(span.attributes).map(([key, value]) =>
        <div key={key}><dt>{t('operate.data', { value: key })}</dt><dd>{t('operate.data', { value: String(value) })}</dd></div>)}</dl></Stack>}
    <Row>{linksOf(span).map(link => <SectionLink key={link.kind} id={id} section={link.kind === 'rule' ? 'rules' : 'hooks'}
      label={t('operate.trace.' + link.kind, { name: link.name })} search={{ [link.kind]: link.name }} />)}</Row>
  </SettingsSection>
}
