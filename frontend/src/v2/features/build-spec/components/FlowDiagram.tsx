import dagre from '@dagrejs/dagre'
import { Background, Controls, MarkerType, Position, ReactFlow } from '@xyflow/react'
import type { Edge, Node } from '@xyflow/react'
import { useT } from '../../../i18n'
import '@xyflow/react/dist/style.css'

export type DiagramNode = { id: string; label: string; initial?: boolean }
export type DiagramEdge = { id: string; source: string; target: string; label: string; selection?: string; active?: boolean }

export default function FlowDiagram({ nodes, edges, onSelect, label }: {
  nodes: DiagramNode[]; edges: DiagramEdge[]; onSelect?: (edge: string) => void; label: string
}) {
  const t = useT()
  const graph = new dagre.graphlib.Graph({ multigraph: true })
  // gate-exempt: Dagre requires numeric geometry for its graph layout.
  const size = { width: 172, height: 58 }
  // gate-exempt: Dagre requires numeric spacing for its graph layout.
  graph.setGraph({ rankdir: 'LR', ranksep: 96, nodesep: 48 })
  graph.setDefaultEdgeLabel(() => ({}))
  for (const node of nodes) graph.setNode(node.id, size)
  for (const edge of edges) graph.setEdge(edge.source, edge.target, {}, edge.id)
  dagre.layout(graph)
  const positioned: Node[] = nodes.map(node => {
    const { x, y } = graph.node(node.id)
    return {
      id: node.id, data: { label: node.label }, position: { x: x - size.width / 2, y: y - size.height / 2 },
      sourcePosition: Position.Right, targetPosition: Position.Left, className: node.initial ? 'v2-build-initial' : undefined,
      focusable: false, ariaLabel: node.label, draggable: false,
    }
  })
  const links: Edge[] = edges.map(edge => ({
    id: edge.id, source: edge.source, target: edge.target, label: edge.label,
    type: 'smoothstep', focusable: false, selected: edge.active, ariaLabel: edge.label,
    markerEnd: { type: MarkerType.ArrowClosed }, className: onSelect ? 'v2-build-edge' : undefined,
  }))
  return <ReactFlow key={JSON.stringify([nodes.map(node => node.id), links.map(edge => [edge.source, edge.target])])}
    aria-label={label} nodes={positioned} edges={links} minZoom={0.3} maxZoom={1.5} fitView fitViewOptions={{ padding: 0.2 }}
    nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} nodesFocusable={false} edgesFocusable={false}
    disableKeyboardA11y preventScrolling={false} onEdgeClick={(_, edge) => {
      const selection = edges.find(item => item.id === edge.id)?.selection
      if (selection) onSelect?.(selection)
    }} ariaLabelConfig={{
      'controls.ariaLabel': t('buildSpec.diagramControls'),
      'controls.zoomIn.ariaLabel': t('buildSpec.zoomIn'),
      'controls.zoomOut.ariaLabel': t('buildSpec.zoomOut'),
      'controls.fitView.ariaLabel': t('buildSpec.fitView'),
    }}>
    <Background /><Controls showInteractive={false} />
  </ReactFlow>
}
