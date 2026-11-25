import type { ReactNode } from 'react'
import { useT } from '../../../i18n'
import { Form } from '../../../patterns'
import type { FormField } from '../../../patterns'
import { CodeBlock, Disclosure, Grid, Row, Stack } from '../../../ui'
import { geographicIssue } from '../../../validators/operateRuntime'
import { parseDegrees } from '../../../../shell/operations/opsLogic'
import { data, field, key, Pick, text } from './Runtime'
import { SectionLink, useOperateSearch } from './Common'
import type { Session } from '../api/live'
import type { Coordinates, Point } from '../api/tools'

export function ToolsLinks({ session, sections }: { session: Session; sections: string[] }) {
  const t = useT()
  return <Row>{sections.map(section => <SectionLink key={section} id={session.projectId} section={section} label={t(key(section === 'places' ? 'placesLink' : section))} />)}</Row>
}

export function JsonDetails({ label, value }: { label: string; value: unknown }) {
  const t = useT()
  return <Disclosure label={t(key(label))}><CodeBlock code={data(t, JSON.stringify(value, null, 2))} /></Disclosure>
}

export function PageSize({ value, onChange }: { value: number; onChange: (size: string) => void }) {
  const t = useT()
  return <Pick label={t(key('pageSize'))} value={String(value)} options={[20, 50, 100, 200].map(size =>
    ({ value: String(size), label: t(key('value'), { value: size }) }))} onChange={onChange} />
}

export function useListSize(fallback: number) {
  const { search, change } = useOperateSearch()
  const size = [20, 50, 100, 200].includes(Number(search.limit)) ? Number(search.limit) : fallback
  return { size, pickSize: (limit: string) => change({ limit, page: undefined }) }
}

export function pointFields(t: ReturnType<typeof useT>, prefix: string, defaults?: Coordinates) {
  return (['lat', 'lng'] as const).map(axis => ({
    ...field(t, axis, { value: defaults?.[axis], validate: value => geographicIssue(value, axis === 'lat' ? 90 : 180) }),
    name: prefix + axis,
  }))
}

export function readPoint(form: FormData, prefix: string): Point {
  return {
    lat_micro: parseDegrees(text(form, prefix + 'lat'), 90)!,
    lng_micro: parseDegrees(text(form, prefix + 'lng'), 180)!,
  }
}

export const world = { min_lat_micro: -90_000_000, min_lng_micro: -180_000_000, max_lat_micro: 90_000_000, max_lng_micro: 180_000_000 }

export function PointGroup({ label, children }: { label: string; children: ReactNode }) {
  const t = useT()
  return <fieldset><legend>{t(key(label))}</legend><Stack>{children}</Stack></fieldset>
}

export function FilterForm({ fields, onSubmit }: { fields: FormField[]; onSubmit: (form: FormData) => void }) {
  const t = useT()
  return <Form fields={fields} submitLabel={t(key('apply'))} layout={controls => <Grid>{Object.values(controls)}</Grid>} onSubmit={onSubmit} />
}
