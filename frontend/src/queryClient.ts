import { QueryClient } from '@tanstack/react-query'

/** Shared TanStack Query client. Nothing reads from it yet (Cycle 0 prep, no screen changes);
 *  new screens in later cycles fetch through it instead of ad-hoc useEffect calls. */
export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 15_000 } },
})
