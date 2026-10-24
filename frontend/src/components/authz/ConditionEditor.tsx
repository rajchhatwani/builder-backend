import type { Operand, PolicyCondition, PolicyGroup, PolicyLeaf } from '../../api/types'
import {
  ENV_ATTRIBUTES,
  KIND_LABELS,
  OPS,
  emptyGroup,
  emptyLeaf,
  groupKey,
  isGroup,
  literalToText,
  operandKind,
  operandName,
  parseLiteral,
  resourceKind,
  type Catalogue,
  type OperandKind,
} from './policyModel'

const MAX_DEPTH = 4

interface Context {
  catalogue: Catalogue
  /** Entities the policy's actions reach: record attributes are offered for these. */
  entities: string[]
}

function OperandEditor({
  operand,
  onChange,
  ctx,
  listValue,
  hintKind,
}: {
  operand: Operand
  onChange: (o: Operand) => void
  ctx: Context
  listValue: boolean
  /** Kind of the other side, used to turn typed text into a number or true/false. */
  hintKind: string | undefined
}) {
  const kind = operandKind(operand)
  const name = operandName(operand)

  const recordAttributes = [...new Set(ctx.entities.flatMap((e) => Object.keys(ctx.catalogue.resource[e] ?? {})))].sort()
  const subjectAttributes = Object.keys(ctx.catalogue.subject)

  function changeKind(next: OperandKind) {
    if (next === 'literal') onChange({ literal: '' })
    else if (next === 'subject') onChange({ subject: 'id' })
    else if (next === 'env') onChange({ env: 'hour_utc' })
    else onChange({ resource: recordAttributes[0] ?? '' })
  }

  return (
    <span style={{ display: 'inline-flex', gap: 'var(--space-1)', alignItems: 'center', flexWrap: 'wrap' }}>
      <select aria-label="Compare what" value={kind} onChange={(e) => changeKind(e.target.value as OperandKind)}>
        {(Object.keys(KIND_LABELS) as OperandKind[]).map((k) => (
          <option key={k} value={k}>
            {KIND_LABELS[k]}
          </option>
        ))}
      </select>
      {kind === 'subject' && (
        <select aria-label="Attribute of the person" value={name} onChange={(e) => onChange({ subject: e.target.value })}>
          {subjectAttributes.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
          {!subjectAttributes.includes(name) && <option value={name}>{name} (unknown)</option>}
        </select>
      )}
      {kind === 'resource' && (
        <select aria-label="Attribute of the record" value={name} onChange={(e) => onChange({ resource: e.target.value })}>
          {recordAttributes.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
          {!recordAttributes.includes(name) && <option value={name}>{name || 'choose…'}</option>}
        </select>
      )}
      {kind === 'env' && (
        <select aria-label="Attribute of the moment" value={name} onChange={(e) => onChange({ env: e.target.value })}>
          {ENV_ATTRIBUTES.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>
      )}
      {kind === 'literal' && (
        <input
          aria-label="Value"
          value={literalToText((operand as { literal: unknown }).literal)}
          placeholder={listValue ? 'a, b, c' : 'value'}
          style={{ minWidth: '10rem' }}
          onChange={(e) => onChange({ literal: parseLiteral(e.target.value, listValue, hintKind) })}
        />
      )}
    </span>
  )
}

function LeafEditor({ leaf, onChange, onRemove, ctx }: { leaf: PolicyLeaf; onChange: (l: PolicyLeaf) => void; onRemove: () => void; ctx: Context }) {
  const op = OPS.find((o) => o.id === leaf.op) ?? OPS[0]
  const leftKind = operandKind(leaf.left) === 'resource' ? resourceKind(ctx.catalogue, ctx.entities, operandName(leaf.left)) : undefined
  const rightKind =
    leaf.right && operandKind(leaf.right) === 'resource' ? resourceKind(ctx.catalogue, ctx.entities, operandName(leaf.right)) : undefined

  return (
    <div
      className="cond-row"
      style={{
        display: 'flex',
        gap: 'var(--space-2)',
        alignItems: 'center',
        flexWrap: 'wrap',
        padding: 'var(--space-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
      }}
    >
      <OperandEditor
        operand={leaf.left}
        ctx={ctx}
        listValue={false}
        hintKind={rightKind}
        onChange={(left) => onChange({ ...leaf, left })}
      />
      <select
        aria-label="Comparison"
        value={leaf.op}
        onChange={(e) => {
          const next = OPS.find((o) => o.id === e.target.value) ?? OPS[0]
          if (next.unary) {
            const { right: _drop, ...rest } = leaf
            void _drop
            onChange({ ...rest, op: next.id })
          } else {
            onChange({ ...leaf, op: next.id, right: leaf.right ?? { literal: '' } })
          }
        }}
      >
        {OPS.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
      {!op.unary && leaf.right && (
        <OperandEditor
          operand={leaf.right}
          ctx={ctx}
          listValue={Boolean(op.list)}
          hintKind={leftKind}
          onChange={(right) => onChange({ ...leaf, right })}
        />
      )}
      <button type="button" className="outline small" aria-label="Remove this comparison" onClick={onRemove}>
        Remove
      </button>
    </div>
  )
}

function GroupEditor({
  group,
  onChange,
  onRemove,
  ctx,
  depth,
}: {
  group: PolicyGroup
  onChange: (g: PolicyGroup) => void
  onRemove: (() => void) | null
  ctx: Context
  depth: number
}) {
  const key = groupKey(group)
  const children = group[key] ?? []

  function setChildren(next: PolicyCondition[]) {
    onChange(key === 'all' ? { all: next } : { any: next })
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
        paddingInlineStart: depth > 0 ? 'var(--space-3)' : 0,
        borderInlineStart: depth > 0 ? '2px solid var(--border)' : 'none',
      }}
    >
      <div className="cond-row" style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
        <span>Match</span>
        <select
          aria-label="All or any"
          value={key}
          onChange={(e) => onChange(e.target.value === 'all' ? { all: children } : { any: children })}
        >
          <option value="all">all of these</option>
          <option value="any">any of these</option>
        </select>
        {onRemove && (
          <button type="button" className="outline small" onClick={onRemove}>
            Remove group
          </button>
        )}
      </div>
      {children.map((child, i) =>
        isGroup(child) ? (
          <GroupEditor
            key={i}
            group={child}
            ctx={ctx}
            depth={depth + 1}
            onChange={(g) => setChildren(children.map((c, j) => (j === i ? g : c)))}
            onRemove={() => setChildren(children.filter((_, j) => j !== i))}
          />
        ) : (
          <LeafEditor
            key={i}
            leaf={child}
            ctx={ctx}
            onChange={(l) => setChildren(children.map((c, j) => (j === i ? l : c)))}
            onRemove={() => setChildren(children.filter((_, j) => j !== i))}
          />
        ),
      )}
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <button type="button" className="outline small" onClick={() => setChildren([...children, emptyLeaf()])}>
          + Add a comparison
        </button>
        {depth < MAX_DEPTH - 1 && (
          <button type="button" className="outline small" onClick={() => setChildren([...children, emptyGroup(key === 'all' ? 'any' : 'all')])}>
            + Add a group
          </button>
        )}
      </div>
    </div>
  )
}

/** Builds a policy condition without typing JSON. `null` means the policy always applies. */
export function ConditionEditor({
  value,
  onChange,
  catalogue,
  entities,
}: {
  value: PolicyCondition | null
  onChange: (v: PolicyCondition | null) => void
  catalogue: Catalogue
  entities: string[]
}) {
  const ctx: Context = { catalogue, entities }
  if (value === null) {
    return (
      <div>
        <p className="muted small-text">
          No condition: the policy applies to every request it names. Add a condition to limit it.
        </p>
        <button type="button" className="outline small" onClick={() => onChange(emptyGroup())}>
          + Add a condition
        </button>
      </div>
    )
  }
  const root: PolicyGroup = isGroup(value) ? value : { all: [value] }
  return (
    <div>
      <GroupEditor group={root} ctx={ctx} depth={0} onChange={onChange} onRemove={null} />
      <button type="button" className="outline small" style={{ marginBlockStart: 'var(--space-2)' }} onClick={() => onChange(null)}>
        Remove the whole condition
      </button>
    </div>
  )
}
