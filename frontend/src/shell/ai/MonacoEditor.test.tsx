import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import MonacoEditor from './MonacoEditor'
import { mount, q } from './testUtils'

// Only the Monaco module itself is faked; MonacoEditor's own wiring is what is under test.
const ed = vi.hoisted(() => ({ props: null as null | Record<string, any>, cmds: [] as Array<[number, () => void]> }))
vi.mock('@monaco-editor/react', () => ({
  default: (p: Record<string, any>) => {
    ed.props = p
    p.onMount?.({ addCommand: (k: number, fn: () => void) => ed.cmds.push([k, fn]) }, { KeyMod: { CtrlCmd: 2048 }, KeyCode: { KeyS: 49 } })
    return createElement('div', { 'data-testid': 'monaco-stub' })
  },
}))
vi.mock('./monacoSetup', () => ({}))

describe('MonacoEditor', () => {
  it('passes path, language, value and a read-only/aria contract to Monaco', async () => {
    await mount(createElement(MonacoEditor, { path: 'a/b.py', language: 'python', value: 'x = 1', readOnly: true, onChange: vi.fn(), onSave: vi.fn(), label: 'Read-only editor for a/b.py' }))
    expect(q('code-editor')?.getAttribute('aria-label')).toBe('Read-only editor for a/b.py')
    expect(ed.props).toMatchObject({ path: 'a/b.py', language: 'python', value: 'x = 1' })
    expect(ed.props!.options).toMatchObject({ readOnly: true, ariaLabel: 'Read-only editor for a/b.py', minimap: { enabled: false } })
  })
  it('maps an undefined change to an empty string and forwards real changes', async () => {
    const onChange = vi.fn()
    await mount(createElement(MonacoEditor, { path: 'p', language: 'json', value: '', readOnly: false, onChange, onSave: vi.fn(), label: 'l' }))
    ed.props!.onChange('new text'); ed.props!.onChange(undefined)
    expect(onChange.mock.calls).toEqual([['new text'], ['']])
    expect(ed.props!.options.readOnly).toBe(false)
  })
  it('registers Ctrl/Cmd+S that triggers onSave', async () => {
    const onSave = vi.fn()
    ed.cmds.length = 0
    await mount(createElement(MonacoEditor, { path: 'p', language: 'json', value: '', readOnly: false, onChange: vi.fn(), onSave, label: 'l' }))
    expect(ed.cmds).toHaveLength(1)
    expect(ed.cmds[0][0]).toBe(2048 | 49)
    ed.cmds[0][1]()
    expect(onSave).toHaveBeenCalledTimes(1)
  })
})
