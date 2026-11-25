export const orgTabs = ['people', 'invites', 'projects', 'plan', 'audit', 'sso', 'security', 'ai', 'usage', 'registry'] as const
export type OrgTab = typeof orgTabs[number]
export const isOrgTab = (value: unknown): value is OrgTab => orgTabs.some(tab => tab === value)

export type OrgSearch = {
  tab?: OrgTab
  page?: number
  past?: true
  checkout?: 'success' | 'cancel'
  sso_test?: string
}

export function orgSearch(search: Record<string, unknown>): OrgSearch {
  return {
    tab: isOrgTab(search.tab) && search.tab !== 'people' ? search.tab : undefined,
    page: typeof search.page === 'number' && Number.isSafeInteger(search.page) && search.page > 1 && search.page <= 1_000_000 ? search.page : undefined,
    past: search.past === true ? true : undefined,
    checkout: search.checkout === 'success' || search.checkout === 'cancel' ? search.checkout : undefined,
    sso_test: typeof search.sso_test === 'string' && /^[a-z_]{1,64}$/.test(search.sso_test) ? search.sso_test : undefined,
  }
}

