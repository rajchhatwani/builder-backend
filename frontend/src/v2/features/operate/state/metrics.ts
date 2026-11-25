import type { FilterForm, MetricForm, ReportForm } from '../../../../shell/metrics/metricsLogic'

type Draft<T> = { value: T; touched: string[]; submitted: boolean }
type Action<T> =
  | { type: 'update'; value: Partial<T> }
  | { type: 'touch'; field: string }
  | { type: 'submit' }

export const createDraft = <T>(value: T): Draft<T> => ({ value, touched: [], submitted: false })

function edit<T>(state: Draft<T>, action: Action<T>): Draft<T> {
  switch (action.type) {
    case 'update': return { ...state, value: { ...state.value, ...action.value } }
    case 'touch': return state.touched.includes(action.field) ? state : { ...state, touched: [...state.touched, action.field] }
    case 'submit': return { ...state, submitted: true }
  }
}

type MetricEdit = Action<MetricForm>
  | { type: 'filter-update'; index: number; value: Partial<FilterForm> }
  | { type: 'filter-remove'; index: number }
  | { type: 'filter-add'; filter: FilterForm }

export function metricDraft(state: Draft<MetricForm>, action: MetricEdit): Draft<MetricForm> {
  const { filters } = state.value
  switch (action.type) {
    case 'filter-update':
      return edit(state, { type: 'update', value: { filters: filters.map((filter, i) => i === action.index ? { ...filter, ...action.value } : filter) } })
    case 'filter-remove':
      return edit({ ...state, touched: state.touched.filter(field => !field.startsWith('filter-')) },
        { type: 'update', value: { filters: filters.filter((_, index) => index !== action.index) } })
    case 'filter-add':
      return edit(state, { type: 'update', value: { filters: [...filters, action.filter] } })
    default: return edit(state, action)
  }
}

type ReportDraft = Draft<ReportForm> & { custom?: boolean }

export const createReportDraft = (value: ReportForm): ReportDraft => createDraft(value)

export function reportDraft(state: ReportDraft, action: Action<ReportForm> & { custom?: boolean }): ReportDraft {
  const next = edit(state, action)
  return { ...next, custom: action.custom ?? state.custom }
}
