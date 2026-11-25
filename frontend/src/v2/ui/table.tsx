import type { ReactNode } from 'react'

export type TableColumn = { id: string; label: string; heading?: ReactNode; sort?: 'ascending' | 'descending' }
export type TableRow = { id: string; cells: ReactNode[]; testId?: string; status?: string }

export function Table({ label, columns, rows }: { label: string; columns: TableColumn[]; rows: TableRow[] }) {
  return (
    <div className="v2-table-container">
      <table className="v2-table" role="table" aria-label={label}>
        <thead role="rowgroup">
          <tr role="row">
            {columns.map(column => <th key={column.id} role="columnheader" scope="col" aria-sort={column.sort}>
              {column.heading
                ? <><span className="v2-table-heading">{column.heading}</span><span className="v2-cell-label">{column.label}</span></>
                : column.label}
            </th>)}
          </tr>
        </thead>
        <tbody role="rowgroup">
          {rows.map(row => (
            <tr key={row.id} role="row" data-testid={row.testId} data-status={row.status}>
              {columns.map((column, index) => (
                <td key={column.id} role="cell">
                  <span className="v2-cell-label" aria-hidden>{column.label}</span>
                  {row.cells[index]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
