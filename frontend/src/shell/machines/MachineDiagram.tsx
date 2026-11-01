import '@xyflow/react/dist/style.css'
import {
  BaseEdge,
  Controls,
  Handle,
  Position,
  EdgeLabelRenderer,
  ReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { useMemo } from 'react'
import type { StateMachineBody } from '../../api/types'
import { layoutMachine } from './layout'

/** Read-only diagram of one state machine (React Flow, positions from dagre). Lazy-loaded by
 *  MachinesPage so this chunk (and the React Flow CSS) is not part of the main bundle. */
interface Props {
  machine: StateMachineBody
  selected: string | null
  onSelect: (transition: string) => void
}

interface EdgeData extends Record<string, unknown> {
  transition: string
  auto: boolean
  active: boolean
  /** Route and label position computed by dagre (see layout.ts). */
  points: { x: number; y: number }[]
  label: { x: number; y: number }
  onSelect: (transition: string) => void
}

/** Smooth path through dagre's points (quadratic curves between segment midpoints). */
export function pathThrough(points: { x: number; y: number }[]): string {
  if (points.length < 3) return points.map((p, i) => `${i ? 'L' : 'M'} ${p.x},${p.y}`).join(' ')
  const mid = (a: { x: number; y: number }, b: { x: number; y: number }) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
  let d = `M ${points[0].x},${points[0].y}`
  const first = mid(points[0], points[1])
  d += ` L ${first.x},${first.y}`
  for (let i = 1; i < points.length - 1; i++) {
    const m = mid(points[i], points[i + 1])
    d += ` Q ${points[i].x},${points[i].y} ${m.x},${m.y}`
  }
  const last = points[points.length - 1]
  return `${d} L ${last.x},${last.y}`
}

function StateNode({ data }: NodeProps<Node<{ label: string }>>) {
  return (
    <>
      <Handle type="target" position={Position.Top} className="machine-handle" isConnectable={false} />
      {data.label}
      <Handle type="source" position={Position.Bottom} className="machine-handle" isConnectable={false} />
    </>
  )
}

function TransitionEdge({ id, data }: EdgeProps<Edge<EdgeData>>) {
  const d = data!
  return (
    <>
      <BaseEdge
        id={id}
        path={pathThrough(d.points)}
        markerEnd="url(#machine-arrow)"
        interactionWidth={16}
        className={`machine-edge${d.active ? ' machine-edge-active' : ''}${d.auto ? ' machine-edge-auto' : ''}`}
      />
      <EdgeLabelRenderer>
        <button
          type="button"
          className={`machine-edge-label nodrag nopan${d.active ? ' machine-edge-label-active' : ''}`}
          style={{ transform: `translate(-50%, -50%) translate(${d.label.x}px, ${d.label.y}px)` }}
          aria-pressed={d.active}
          data-transition={d.transition}
          onClick={() => d.onSelect(d.transition)}
        >
          {d.transition}
          {d.auto && <span className="machine-auto"> auto</span>}
        </button>
      </EdgeLabelRenderer>
    </>
  )
}

const EDGE_TYPES = { transition: TransitionEdge }
const NODE_TYPES = { state: StateNode }

export default function MachineDiagram({ machine, selected, onSelect }: Props) {
  const flow = useMemo(() => {
    const laid = layoutMachine(machine)
    const byName = new Map((machine.transitions ?? []).map((t) => [t.name, t]))
    const nodes: Node[] = laid.nodes.map((n) => ({
      id: n.id,
      position: { x: n.x, y: n.y },
      width: n.width,
      height: n.height,
      type: 'state',
      data: { label: n.id },
      className: n.initial ? 'machine-node machine-node-initial' : 'machine-node',
      draggable: false,
      connectable: false,
      focusable: false,
    }))
    const edges: Edge<EdgeData>[] = laid.edges.map((e) => {
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        type: 'transition',
        focusable: false,
        data: {
          transition: e.transition,
          auto: !!byName.get(e.transition)?.auto,
          active: selected === e.transition,
          points: e.points,
          label: e.label,
          onSelect,
        },
      }
    })
    return { nodes, edges }
  }, [machine, selected, onSelect])

  return (
    <div className="machine-flow" data-testid="machine-diagram">
      <svg width="0" height="0" aria-hidden="true" focusable="false" style={{ position: 'absolute' }}>
        <defs>
          <marker id="machine-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
          </marker>
        </defs>
      </svg>
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        disableKeyboardA11y
        minZoom={0.3}
        maxZoom={1.5}
        onEdgeClick={(_, edge) => onSelect((edge.data as EdgeData).transition)}
      >
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
