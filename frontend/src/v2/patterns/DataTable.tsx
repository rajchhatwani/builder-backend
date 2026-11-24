import type { ReactNode } from 'react'
import { useT } from '../i18n'
import { Button, EmptyState, Input, Pagination, Row, Stack, Table } from '../ui'
import type { TableColumn, TableRow } from '../ui'

export type DataTableState = { filter: string; page: number; sort?: { id: string; direction: 'ascending' | 'descending' } }

export function DataTable({ label, columns, rows, state, pages, onChange, emptyAction }: {
  label: string
  columns: (TableColumn & { sortable?: boolean })[]
  rows: TableRow[]
  state: DataTableState
  pages: number
  onChange: (next: DataTableState) => void
  emptyAction?: ReactNode
}) {
  const t = useT()
  const tableColumns = columns.map(column => {
    const direction = state.sort?.id === column.id ? state.sort.direction : undefined
    return {
      ...column, sort: direction,
      heading: column.sortable ? <Button variant="ghost" onClick={() => sort(column.id)}>{column.label}{direction && <span aria-hidden>{direction === 'ascending' ? '↑' : '↓'}</span>}</Button> : column.heading,
    }
  })
  function sort(id: string) {
    onChange({ ...state, page: 1, sort: { id, direction: state.sort?.id === id && state.sort.direction === 'ascending' ? 'descending' : 'ascending' } })
  }
  return (
    <Stack className="v2-data-table">
      <Row>
        <Input type="search" aria-label={t('common.filterTable', { label })} placeholder={t('common.filter')} value={state.filter}
          onChange={event => onChange({ ...state, filter: event.target.value, page: 1 })} />
        {columns.some(column => column.sortable) && (
          <Row className="v2-mobile-sort">
            {columns.filter(column => column.sortable).map(column => (
              <Button key={column.id} onClick={() => sort(column.id)} aria-pressed={state.sort?.id === column.id}>
                {t('common.sortBy', { label: column.label })}{state.sort?.id === column.id && <span aria-hidden>{state.sort.direction === 'ascending' ? '↑' : '↓'}</span>}
              </Button>
            ))}
          </Row>
        )}
      </Row>
      {rows.length ? <Table label={label} columns={tableColumns} rows={rows} /> : <EmptyState title={t('common.noResults')} action={emptyAction ?? (
        state.filter ? <Button onClick={() => onChange({ ...state, filter: '', page: 1 })}>{t('common.clearFilter')}</Button> : undefined
      )} />}
      {pages > 1 && <Pagination label={label} page={state.page} pages={pages} onChange={page => onChange({ ...state, page })} />}
    </Stack>
  )
}
