import { graphlib, layout } from '@dagrejs/dagre'
import { useId, useMemo } from 'react'
import type { Edge, Node } from '../model'

const boxWidth = 192
const boxHeight = 60
const memberHeight = 19
const maxMembers = 5

function height(node: Node) {
  return boxHeight + Math.min(node.members?.length ?? 0, maxMembers) * memberHeight
}

export default function DiagramCanvas({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) {
  const arrow = useId()
  const positions = useMemo(() => {
    const graph = new graphlib.Graph({ multigraph: true })
    graph.setGraph({ rankdir: 'LR', nodesep: 20, ranksep: 48, marginx: 8, marginy: 8 })
    graph.setDefaultEdgeLabel(() => ({}))
    nodes.forEach((node, i) => graph.setNode(String(i), { width: boxWidth, height: height(node) }))
    edges.forEach(({ from, to }, i) => {
      if (nodes[from] && nodes[to]) graph.setEdge(String(from), String(to), {}, String(i))
    })
    layout(graph)
    return {
      nodes: graph.nodes().map(id => graph.node(id)),
      paths: graph.edges().map(edge => graph.edge(edge).points.map((point: { x: number; y: number }) => [point.x, point.y].join(',')).join(' ')),
      width: graph.graph().width,
      height: graph.graph().height,
    }
  }, [nodes, edges])

  return <svg className="v2-diagrams-canvas" width={positions.width} height={positions.height}
    viewBox={[0, 0, positions.width, positions.height].join(' ')} aria-hidden>
    <defs>
      <marker id={arrow} markerWidth={8} markerHeight={8} refX={7} refY={4} orient="auto">
        <path d="M0 0L8 4L0 8Z" className="v2-diagrams-arrow" />
      </marker>
    </defs>
    {positions.paths.map((points, i) => <polyline key={i} points={points} className="v2-diagrams-edge" markerEnd={`url(#${arrow})`} />)}
    {nodes.map((node, i) => {
      const { x, y } = positions.nodes[i]
      const boxHeight = height(node)
      return <foreignObject key={i} x={x - boxWidth / 2} y={y - boxHeight / 2} width={boxWidth} height={boxHeight}>
        <div className="v2-diagrams-node">
          <strong>{node.name}</strong>{node.detail && <span>{node.detail}</span>}
          {node.members?.slice(0, maxMembers).map((member, i) => <span key={i}>{member}</span>)}
        </div>
      </foreignObject>
    })}
  </svg>
}
