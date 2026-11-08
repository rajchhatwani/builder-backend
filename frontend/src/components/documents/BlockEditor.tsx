import { useUi } from '../Ui'
import { BLOCK_LABELS, columnsToText, newBlock, rowsToText, textToColumns, textToRows, type Block, type BlockType } from './blocks'

const MAX_IMAGE_BYTES = 200_000

function BlockFields({ block, onChange }: { block: Block; onChange: (b: Block) => void }) {
  const { toast } = useUi()
  const set = (patch: Record<string, unknown>) => onChange({ ...block, ...patch })
  switch (block.type) {
    case 'heading':
      return (
        <div className="field-grid">
          <label>
            Text
            <input value={String(block.text ?? '')} onChange={(e) => set({ text: e.target.value })} />
          </label>
          <label>
            Size
            <select value={Number(block.level ?? 1)} onChange={(e) => set({ level: Number(e.target.value) })}>
              <option value={1}>Large</option>
              <option value={2}>Medium</option>
              <option value={3}>Small</option>
            </select>
          </label>
        </div>
      )
    case 'paragraph':
    case 'signature':
      return (
        <label>
          Text
          <textarea rows={block.type === 'paragraph' ? 3 : 1} value={String(block.text ?? '')} onChange={(e) => set({ text: e.target.value })} />
        </label>
      )
    case 'kv':
    case 'totals':
      return (
        <label>
          One row per line, written <code>label :: value</code>
          <textarea rows={4} value={rowsToText(block.rows)} onChange={(e) => set({ rows: textToRows(e.target.value) })} />
        </label>
      )
    case 'table':
      return (
        <>
          <label>
            Name of the list in your data
            <input value={String(block.source ?? '')} onChange={(e) => set({ source: e.target.value })} />
          </label>
          <label>
            One column per line, written <code>header :: value :: left|right|center :: width</code> (use <code>{'{{item.field}}'}</code>)
            <textarea rows={5} value={columnsToText(block.columns)} onChange={(e) => set({ columns: textToColumns(e.target.value) })} />
          </label>
        </>
      )
    case 'spacer':
      return (
        <label style={{ maxWidth: '10rem' }}>
          Height (mm)
          <input type="number" min={1} max={100} value={Number(block.height_mm ?? 6)} onChange={(e) => set({ height_mm: Number(e.target.value) })} />
        </label>
      )
    case 'qr':
      return (
        <div className="field-grid">
          <label>
            Content
            <input value={String(block.value ?? '')} onChange={(e) => set({ value: e.target.value })} />
          </label>
          <label>
            Size (mm)
            <input type="number" min={10} max={80} value={Number(block.size_mm ?? 28)} onChange={(e) => set({ size_mm: Number(e.target.value) })} />
          </label>
        </div>
      )
    case 'image':
      return (
        <div className="field-grid">
          <label>
            PNG or JPEG, at most 200 KB
            <input
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                if (file.size > MAX_IMAGE_BYTES) {
                  toast('That image is larger than 200 KB. Use a smaller logo.', 'danger')
                  return
                }
                const reader = new FileReader()
                reader.onload = () => set({ data_base64: String(reader.result).split(',')[1] ?? '' })
                reader.readAsDataURL(file)
              }}
            />
          </label>
          <label>
            Width (mm)
            <input type="number" min={5} max={180} value={Number(block.width_mm ?? 40)} onChange={(e) => set({ width_mm: Number(e.target.value) })} />
          </label>
          <label>
            Align
            <select value={String(block.align ?? 'left')} onChange={(e) => set({ align: e.target.value })}>
              <option value="left">Left</option>
              <option value="center">Center</option>
              <option value="right">Right</option>
            </select>
          </label>
          <p className="muted small-text">{block.data_base64 ? 'An image is set.' : 'No image yet.'}</p>
        </div>
      )
    default:
      return <p className="muted small-text">No settings.</p>
  }
}

/** Edits the list of blocks of a template as a form. */
export function BlockEditor({ blocks, onChange }: { blocks: Block[]; onChange: (b: Block[]) => void }) {
  const move = (i: number, d: number) => {
    const j = i + d
    if (j < 0 || j >= blocks.length) return
    const next = [...blocks]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      {blocks.map((block, i) => (
        <div key={i} className="idp-card" style={{ margin: 0 }}>
          <div className="idp-card-head">
            <strong>{BLOCK_LABELS[block.type] ?? block.type}</strong>
            <span style={{ display: 'flex', gap: 'var(--space-1)' }}>
              <button type="button" className="outline small" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
                ↑
              </button>
              <button type="button" className="outline small" aria-label="Move down" disabled={i === blocks.length - 1} onClick={() => move(i, 1)}>
                ↓
              </button>
              <button type="button" className="outline small" onClick={() => onChange(blocks.filter((_, j) => j !== i))}>
                Remove
              </button>
            </span>
          </div>
          <BlockFields block={block} onChange={(b) => onChange(blocks.map((x, j) => (j === i ? b : x)))} />
        </div>
      ))}
      <label style={{ maxWidth: '18rem' }}>
        Add a block
        <select
          value=""
          onChange={(e) => {
            if (e.target.value) onChange([...blocks, newBlock(e.target.value as BlockType)])
          }}
        >
          <option value="">Choose…</option>
          {(Object.keys(BLOCK_LABELS) as BlockType[]).map((t) => (
            <option key={t} value={t}>
              {BLOCK_LABELS[t]}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
