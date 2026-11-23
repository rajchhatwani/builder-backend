import { Suspense, lazy } from 'react'

// Scalar is large (see F2-5 report): its own chunk, fetched on first view of this tab only.
const ScalarView = lazy(() => import('./ScalarView'))

export function ApiReference({ doc, base }: { doc: Record<string, unknown>; base: string }) {
  return (
    <div className="wb-reference" data-testid="wb-reference">
      <Suspense fallback={<p role="status" aria-live="polite">Loading API reference…</p>}>
        <ScalarView document={doc} origin={base} />
      </Suspense>
    </div>
  )
}
