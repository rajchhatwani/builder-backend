import { createHashHistory, createRootRoute, createRouter } from '@tanstack/react-router'

/** TanStack Router on hash history, prepared but NOT mounted (Cycle 0 prep). The screens still
 *  use the hand-written `parseHash` in App.tsx; the contract test in routes.contract.test.ts
 *  must keep passing while routes migrate one by one, so every existing `#/…` URL keeps working. */
export function createAppRouter() {
  const rootRoute = createRootRoute()
  return createRouter({ routeTree: rootRoute, history: createHashHistory() })
}
