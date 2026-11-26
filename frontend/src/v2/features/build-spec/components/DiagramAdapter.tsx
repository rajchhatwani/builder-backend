import { lazy, Suspense } from 'react'
import { useT } from '../../../i18n'
import { Card, ErrorBoundary, Skeleton } from '../../../ui'
import type { DiagramEdge, DiagramNode } from './FlowDiagram'
import '../build.css'

const Diagram = lazy(() => import('./FlowDiagram'))
export type { DiagramEdge, DiagramNode }

export function DiagramAdapter(props: { nodes: DiagramNode[]; edges: DiagramEdge[]; onSelect?: (edge: string) => void; label: string }) {
  const t = useT()
  return <Card className="v2-build-diagram" aria-label={props.label}>
    <ErrorBoundary><Suspense fallback={<Skeleton lines={6} label={t('buildSpec.diagramLoading')} />}>
      <Diagram {...props} />
    </Suspense></ErrorBoundary>
  </Card>
}
