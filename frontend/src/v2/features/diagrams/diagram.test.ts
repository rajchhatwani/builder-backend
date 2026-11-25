import { expect, it } from 'vitest'
import { catalogue, filterCatalogue } from './catalogue'
import { upcomingTimes } from './cron'
import { buildDiagram } from './sourcedViews'

const translate = (key: string) => key
const spec = {
  entities: [{ name: 'Customer', fields: [] }, { name: 'Invoice', fields: [] }],
  relations: [{ from_entity: 'Customer', to_entity: 'Invoice', kind: 'one_to_many' }],
}

it('keeps all 47 catalogue entries renderable for a partial saved spec', () => {
  expect(catalogue).toHaveLength(47)
  expect(filterCatalogue('OPS').diagrams.some(view => view.id === 'D05')).toBe(false)
  expect(filterCatalogue('other').current).toBe('ALL')
  for (const { id } of catalogue) {
    expect(buildDiagram(id, {}, {}, translate)).toBeDefined()
    expect(buildDiagram(id, spec, {}, translate)).toBeDefined()
  }
  expect(buildDiagram('D05', spec, {}, translate).edges).toEqual([{ from: 0, to: 1, label: 'one_to_many' }])
})

it('skips a missing local time and does not repeat a folded local time', () => {
  const spring = upcomingTimes('30 2 * * *', 'America/New_York', Date.parse('2026-03-08T00:00:00Z'))
  expect(spring?.[0]).toBe(Date.parse('2026-03-09T06:30:00Z'))
  const autumn = upcomingTimes('30 1 * * *', 'America/New_York', Date.parse('2026-11-01T00:00:00Z'))
  expect(autumn?.slice(0, 2)).toEqual([Date.parse('2026-11-01T05:30:00Z'), Date.parse('2026-11-02T06:30:00Z')])
  expect(upcomingTimes('0/2 2 * * *', 'UTC', 0)).toBeUndefined()
})
