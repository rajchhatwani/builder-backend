import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { TracesPage } from './TracesPage'
import { EXAMPLE_TRACE } from './traceLogic'
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: ReturnType<typeof createRoot> | null = null
let host: HTMLElement
async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => { root!.render(createElement(TracesPage, { projectId: 'p1' })) })
}
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const btn = (re: RegExp) => [...host.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''))!
const click = (el: Element) => act(async () => { (el as HTMLElement).click() })
afterEach(() => { act(() => root?.unmount()); host?.remove(); root = null })

function type(value: string) {
  const ta = q('textarea') as HTMLTextAreaElement
  return act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(ta, value)
    ta.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('TracesPage', () => {
  it('shows the empty state first', async () => {
    await mount()
    expect(q('[data-testid=traces-empty]')).not.toBeNull()
    expect(host.querySelectorAll('[data-testid=trace-row]')).toHaveLength(0)
  })

  it('renders every span of the example and marks the error in text', async () => {
    await mount()
    await click(btn(/Load example/))
    const rows = [...host.querySelectorAll('[data-testid=trace-row]')]
    expect(rows).toHaveLength(EXAMPLE_TRACE.spans.length)
    expect(q('[data-testid=trace-summary]')!.textContent).toContain('7 spans over 182 ms')
    const failing = rows.find((r) => /erp\.example/.test(r.textContent ?? ''))!
    expect(failing.textContent).toContain('ERROR')
    expect(q('.trace-scroll')!.getAttribute('tabindex')).toBe('0')
    expect(q('.trace-scroll')!.getAttribute('aria-label')).toBeTruthy()
  })

  it('selects a rule span and links to the rules page', async () => {
    await mount()
    await click(btn(/Load example/))
    const rule = [...host.querySelectorAll('[data-testid=trace-row]')].find((r) => /rule invoice_within_limit/.test(r.textContent ?? ''))!
    await click(rule)
    expect(rule.getAttribute('aria-pressed')).toBe('true')
    const a = q('[data-testid=span-detail] a') as HTMLAnchorElement
    expect(a.getAttribute('href')).toBe('#/p/p1/rules?rule=invoice_within_limit')
    expect(q('[data-testid=span-attrs]')!.textContent).toContain('bb.rule')
  })

  it('links a hook span to the hooks page', async () => {
    await mount()
    await click(btn(/Load example/))
    await click([...host.querySelectorAll('[data-testid=trace-row]')].find((r) => /hook check_po_match/.test(r.textContent ?? ''))!)
    expect((q('[data-testid=span-detail] a') as HTMLAnchorElement).getAttribute('href')).toBe('#/p/p1/hooks?hook=check_po_match')
  })

  it('shows an error for bad JSON and clears it with a good trace', async () => {
    await mount()
    await type('{not json')
    await click(btn(/Show trace/))
    expect(q('[data-testid=trace-error]')!.textContent).toMatch(/not valid JSON/)
    expect(q('[data-testid=traces-empty]')).toBeNull()
    await click(btn(/Load example/))
    expect(q('[data-testid=trace-error]')).toBeNull()
    await click(btn(/^Clear$/))
    expect(q('[data-testid=traces-empty]')).not.toBeNull()
  })

  it('shows warnings for a trace with a missing parent', async () => {
    await mount()
    await type(JSON.stringify({ trace_id: 't', spans: [{ span_id: 'a', parent_span_id: 'zz', name: 'lonely', start_unix_ms: 0, end_unix_ms: 5, status: 'ok' }] }))
    await click(btn(/Show trace/))
    expect(q('[data-testid=trace-warnings]')!.textContent).toMatch(/not in the trace/)
    expect(host.querySelectorAll('[data-testid=trace-row]')).toHaveLength(1)
  })
})
