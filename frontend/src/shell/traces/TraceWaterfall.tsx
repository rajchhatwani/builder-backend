import type { KeyboardEvent } from 'react'
import { formatMs, type WaterfallRow } from './traceLogic'

interface Props {
  rows: WaterfallRow[]
  totalMs: number
  selectedId: string | null
  onSelect: (spanId: string) => void
}

/** One focusable row per span, indented by depth. The bar is decoration; the row's text carries the
 *  name, service, duration and status, so nothing depends on colour or on seeing the bar. */
export function TraceWaterfall({ rows, totalMs, selectedId, onSelect }: Props) {
  const move = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    const items = [...(e.currentTarget.closest('ul')?.querySelectorAll<HTMLButtonElement>('button.trace-row') ?? [])]
    const next = items[items.indexOf(e.currentTarget) + (e.key === 'ArrowDown' ? 1 : -1)]
    if (next) { e.preventDefault(); next.focus() }
  }
  return (
    <div className="trace-scroll" role="region" aria-label="Trace waterfall, scrolls sideways" tabIndex={0}>
      <ul className="trace-rows" aria-label={`${rows.length} spans over ${formatMs(totalMs)}`}>
        {rows.map((r) => {
          const err = r.span.status === 'error'
          return (
            <li key={r.span.span_id}>
              <button
                type="button"
                className={`trace-row${selectedId === r.span.span_id ? ' is-selected' : ''}${err ? ' is-error' : ''}`}
                aria-pressed={selectedId === r.span.span_id}
                data-testid="trace-row"
                onClick={() => onSelect(r.span.span_id)}
                onKeyDown={move}
              >
                <span className="trace-label" style={{ paddingInlineStart: `${Math.min(r.depth, 12) * 1}rem` }}>
                  <span className="trace-name">{r.span.name}</span>
                  {r.span.service && <span className="muted"> {r.span.service}</span>}
                  {err && <strong className="trace-err"> ERROR</strong>}
                  {r.onCriticalPath && <span className="muted"> (critical path)</span>}
                  <span className="muted"> {formatMs(r.durationMs)}</span>
                </span>
                <span className="trace-track" aria-hidden="true">
                  <span
                    className={`trace-bar${err ? ' is-error' : ''}${r.onCriticalPath ? ' is-critical' : ''}`}
                    style={{ insetInlineStart: `${r.offsetPct}%`, inlineSize: `${r.widthPct}%` }}
                  />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
