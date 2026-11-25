type ProjectSearch = { q?: string; owner?: string; health?: 'ready' | 'fix'; sort?: 'oldest'; page?: number }
type AccountSearch = { history?: boolean; page?: number }

export function projectSearch(search: Record<string, unknown>): ProjectSearch {
  return {
    q: typeof search.q === 'string' ? search.q : undefined,
    owner: typeof search.owner === 'string' ? search.owner : undefined,
    health: search.health === 'ready' || search.health === 'fix' ? search.health : undefined,
    sort: search.sort === 'oldest' ? search.sort : undefined,
    page: typeof search.page === 'number' && Number.isSafeInteger(search.page) && search.page > 1 ? search.page : undefined,
  } as const
}

export function accountSearch(search: Record<string, unknown>): AccountSearch {
  return {
    history: search.history === true ? true : undefined,
    page: typeof search.page === 'number' && Number.isSafeInteger(search.page) && search.page > 1 ? search.page : undefined,
  }
}

declare module '@tanstack/react-router' {
  interface HistoryState {
    projectIdea?: string
  }
}
