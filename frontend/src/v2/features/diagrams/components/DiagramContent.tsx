import { lazy, Suspense } from 'react'
import type { ReactNode } from 'react'
import { useT } from '../../../i18n'
import { Button, ErrorBoundary, Row, Skeleton, Stack, Table } from '../../../ui'
import type { Cell, Diagram, DiagramTable } from '../model'

const Canvas = lazy(() => import('./DiagramCanvas'))
const canvasLimit = 100
const tablePageSize = 30

export function cellLabel(cell: Cell, t: ReturnType<typeof useT>) {
  if (cell === true || cell === false) return t(cell ? 'diagrams.words.yes' : 'diagrams.words.no')
  if (cell === undefined || cell === null || cell === '') return t('diagrams.blank')
  return t('diagrams.value', { value: cell })
}

function DiagramRows({ table, fallback, requestedPage, onPage, transform }: {
  table: DiagramTable
  fallback: string
  requestedPage?: number
  onPage: (next: number) => void
  transform?: (value: Cell, column: number, row: Cell[]) => ReactNode
}) {
  const t = useT()
  const totalPages = Math.ceil(table.rows.length / tablePageSize)
  const page = Math.min(requestedPage ?? 1, totalPages)
  const rows = table.rows.slice((page - 1) * tablePageSize, page * tablePageSize)
  const label = table.heading ?? fallback
  return <Stack gap={2}>
    {table.heading && <h3>{table.heading}</h3>}
    <Table label={label} columns={table.columns.map((label, index) => ({ id: String(index), label }))}
      rows={rows.map((row, index) => ({
        id: String(index), cells: row.map((value, column) => transform?.(value, column, row) ?? cellLabel(value, t)),
      }))} />
    {totalPages > 1 && <Row>
      <Button onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label={t('diagrams.previousTable', { table: label })}>
        {t('diagrams.previous')}
      </Button>
      <span>{t('diagrams.tablePage', { page, total: totalPages })}</span>
      <Button onClick={() => onPage(page + 1)} disabled={page >= totalPages} aria-label={t('diagrams.nextTable', { table: label })}>
        {t('diagrams.more')}
      </Button>
    </Row>}
  </Stack>
}

export function DiagramContent({ diagram, title, pages, onPage, heatmap, onFile }: {
  diagram: Diagram
  title: string
  pages?: Record<string, number>
  onPage: (table: string, page: number) => void
  heatmap?: boolean
  onFile?: (path: string) => ReactNode
}) {
  const t = useT()
  const nodes = diagram.nodes ?? []
  const edges = (diagram.edges ?? []).filter(edge => nodes[edge.from] && nodes[edge.to])
  const tables = (diagram.tables ?? []).filter(table => table.rows.length > 0)
  const items = { heading: t('diagrams.items'), columns: [t('diagrams.name'), t('diagrams.detail')],
    rows: nodes.map(node => [node.name, node.detail]) }
  const connections = { heading: t('diagrams.connections'), columns: [t('diagrams.from'), t('diagrams.connection'), t('diagrams.to')],
    rows: edges.map(edge => [nodes[edge.from].name, edge.label, nodes[edge.to].name]) }
  const data = [
    ...(nodes.length ? [{ key: 'nodes', table: items }] : []),
    ...(edges.length ? [{ key: 'edges', table: connections }] : []),
    ...tables.map((table, i) => ({ key: String(i), table })),
    ...(diagram.files?.length ? [{ key: 'files', table: {
      heading: t('diagrams.words.files'), columns: [t('diagrams.words.filePath')], rows: diagram.files.map(path => [path]),
    } }] : []),
  ]
  if (!data.length) return <p className="v2-muted">{t('diagrams.noEntries')}</p>
  return <Stack gap={4}>
    {nodes.length > 0 && nodes.length <= canvasLimit && <div className="v2-diagrams-viewport" role="region" aria-label={t('diagrams.canvas', { title })} tabIndex={0}>
      <ErrorBoundary><Suspense fallback={<Skeleton label={t('diagrams.loadingCanvas')} lines={5} />}>
        <Canvas nodes={nodes} edges={edges} />
      </Suspense></ErrorBoundary>
    </div>}
    {nodes.length > canvasLimit && <p className="v2-muted">{t('diagrams.largeGraph', { count: nodes.length })}</p>}
    {data.map(({ key, table }, i) => <DiagramRows key={key} table={table}
      fallback={title + ' · ' + t('diagrams.tableNumber', { count: i + 1 })}
      requestedPage={pages?.[key]} onPage={page => onPage(key, page)}
      transform={key === 'files' ? value => typeof value === 'string' ? onFile?.(value) : undefined : heatmap ? (value, column) => column > 0 ? <span className="v2-diagrams-matrix-cell"
        data-result={typeof value === 'string' ? value.toLowerCase() : undefined}>{cellLabel(value, t)}</span> : undefined : undefined} />)}
  </Stack>
}
