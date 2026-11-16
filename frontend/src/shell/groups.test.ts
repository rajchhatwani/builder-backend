import { describe, expect, it } from 'vitest'
import { SECTIONS } from '../components/Sidebar'
import { V2_SECTIONS } from './pages'
import { RAIL_GROUPS, filterCommands } from './groups'

describe('v2 rail groups', () => {
  it('lists every existing section and every v2-only page exactly once', () => {
    const grouped = RAIL_GROUPS.flatMap((g) => g.sections).sort()
    expect(new Set(grouped).size).toBe(grouped.length)
    const classic = new Set<string>(SECTIONS.map((s) => s.id))
    expect(V2_SECTIONS.filter((s) => classic.has(s.id)).map((s) => s.id)).toEqual([])
    expect(grouped).toEqual([...SECTIONS.map((s) => s.id), ...V2_SECTIONS.map((s) => s.id)].sort())
  })
  it('has the seven groups in order', () => {
    expect(RAIL_GROUPS.map((g) => g.label)).toEqual(['Home', 'Build with AI', 'Build', 'Secure', 'Connect', 'Operate', 'Ship'])
  })
})

describe('filterCommands', () => {
  const cmds = [
    { id: 'a', label: 'Data model', hint: 'Build', run: () => undefined },
    { id: 'b', label: 'Deploy', hint: 'Ship', run: () => undefined },
  ]
  it('matches every word, case-insensitively', () => {
    expect(filterCommands(cmds, 'data BUILD').map((c) => c.id)).toEqual(['a'])
    expect(filterCommands(cmds, 'zzz')).toEqual([])
    expect(filterCommands(cmds, '  ')).toHaveLength(2)
  })
})
