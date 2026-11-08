import type { ReactNode } from 'react'

/** Who made a thing: a person, or the agent (with a link to its run). */
export function ProvenanceBadge({ author, projectId, runId }: { author: 'ai' | 'human' | string; projectId?: string; runId?: string | null }) {
  if (author === 'ai') {
    return (
      <span className="ai-prov ai-prov-ai" data-testid="prov-ai">
        <span className="badge" title="Written by the build agent">AI</span>
        {projectId && runId && <a href={`#/p/${projectId}/build?run=${runId}`} className="small-text" data-testid="prov-run-link">run {runId.slice(0, 8)}</a>}
      </span>
    )
  }
  return <span className="badge badge-outline ai-prov" data-testid="prov-human" title="Written by a person">{author === 'human' || !author ? 'Human' : author}</span>
}

/** Marks a change that nobody has approved yet. Not colour alone: a label and a dashed edge. */
export function Proposed({ children, label = 'Proposed, not approved yet' }: { children: ReactNode; label?: string }) {
  return (
    <div className="ai-proposed" data-testid="proposed" role="group" aria-label={label}>
      <span className="badge badge-muted">Proposed</span> {children}
    </div>
  )
}
