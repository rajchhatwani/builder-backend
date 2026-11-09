import { useId, useState, type ChangeEvent } from 'react'
import { link } from '../../components/Sidebar'
import { TraceWaterfall } from './TraceWaterfall'
import { EXAMPLE_TRACE, MAX_TRACE_BYTES, formatMs, linkPath, linksOf, parseTrace, type ParsedTrace } from './traceLogic'

export function TracesPage({ projectId }: { projectId: string }) {
  const textId = useId()
  const fileId = useId()
  const [text, setText] = useState('')
  const [trace, setTrace] = useState<ParsedTrace | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const show = (source: string) => {
    const r = parseTrace(source)
    if (r.ok) { setTrace(r.trace); setError(null); setSelected(null) } else { setTrace(null); setError(r.error); setSelected(null) }
  }
  const loadExample = () => {
    const s = JSON.stringify(EXAMPLE_TRACE, null, 2)
    setText(s)
    show(s)
  }
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    if (f.size > MAX_TRACE_BYTES) { setTrace(null); setError('This file is larger than 2 MB. Trim the trace and try again.'); return }
    try {
      const s = await f.text()
      setText(s)
      show(s)
    } catch {
      setTrace(null)
      setError('The file could not be read.')
    }
  }
  const clear = () => { setText(''); setTrace(null); setError(null); setSelected(null) }

  const row = trace?.rows.find((r) => r.span.span_id === selected) ?? null

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Traces</h1>
          <p>See where the time went in one request. Your generated app sends its traces to your own collector, so paste or upload a trace here to read it. Nothing you load is saved or sent anywhere.</p>
        </div>
      </div>

      <section className="card" aria-label="Load a trace">
        <div className="field">
          <label htmlFor={textId}>Trace document (JSON)</label>
          <textarea id={textId} rows={6} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} />
        </div>
        <div className="hstack">
          <button type="button" onClick={() => show(text)}>Show trace</button>
          <button type="button" onClick={loadExample}>Load example</button>
          <button type="button" onClick={clear} disabled={!text && !trace && !error}>Clear</button>
          <label htmlFor={fileId} className="muted">Or upload a .json file</label>
          <input id={fileId} type="file" accept="application/json,.json" onChange={(e) => void onFile(e)} />
        </div>
      </section>

      {error && <div role="alert" className="card" data-testid="trace-error"><strong>This trace could not be shown.</strong> {error}</div>}

      {!trace && !error && (
        <div className="card empty-hero" data-testid="traces-empty">
          <h2>No trace loaded</h2>
          <p>Load the example to see how a request approving an invoice spent its time in the web layer, a rule, a hook and the database.</p>
        </div>
      )}

      {trace && (
        <>
          <p data-testid="trace-summary">
            Trace {trace.traceId}: {trace.rows.length} {trace.rows.length === 1 ? 'span' : 'spans'} over {formatMs(trace.totalMs)}. Spans on the longest path are marked.
          </p>
          {trace.warnings.length > 0 && (
            <div role="status" className="card" data-testid="trace-warnings">
              <strong>Some things were adjusted</strong>
              <ul>{trace.warnings.slice(0, 20).map((w, i) => <li key={i}>{w}</li>)}</ul>
              {trace.warnings.length > 20 && <p className="muted">and {trace.warnings.length - 20} more.</p>}
            </div>
          )}
          <TraceWaterfall rows={trace.rows} totalMs={trace.totalMs} selectedId={selected} onSelect={setSelected} />
          <section className="card" aria-label="Span details" data-testid="span-detail">
            {!row && <p className="muted">Select a span to see its details.</p>}
            {row && (
              <>
                <h2>{row.span.name}</h2>
                <dl>
                  <dt>Service</dt><dd>{row.span.service || 'not given'}</dd>
                  <dt>Status</dt><dd>{row.span.status === 'error' ? 'Error' : 'OK'}</dd>
                  <dt>Started</dt><dd>{formatMs(row.offsetMs)} after the trace began</dd>
                  <dt>Duration</dt><dd>{formatMs(row.durationMs)}</dd>
                  <dt>Span id</dt><dd>{row.span.span_id}</dd>
                </dl>
                {linksOf(row.span).length > 0 && (
                  <ul aria-label="Linked items">
                    {linksOf(row.span).map((l) => (
                      <li key={l.kind}>
                        <a href={link(linkPath(projectId, l))}>Open {l.kind === 'rule' ? 'Rules' : 'Hooks'} for {l.kind} {l.name}</a>
                      </li>
                    ))}
                  </ul>
                )}
                <h3>Attributes</h3>
                {Object.keys(row.span.attributes).length === 0
                  ? <p className="muted">This span has no attributes.</p>
                  : <dl data-testid="span-attrs">{Object.entries(row.span.attributes).flatMap(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{String(v)}</dd>])}</dl>}
              </>
            )}
          </section>
        </>
      )}
    </>
  )
}
