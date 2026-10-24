/** Plain-data shape of a PDF template (what the engine renders) and helpers to edit it as text. */

export type BlockType = 'heading' | 'paragraph' | 'kv' | 'table' | 'totals' | 'spacer' | 'rule' | 'page_break' | 'image' | 'signature' | 'qr'

export interface Block {
  type: BlockType
  [key: string]: unknown
}

export interface DocTemplateData {
  title?: string
  page?: { size?: string; orientation?: string; margin_mm?: number }
  header?: string
  footer?: string
  blocks: Block[]
}

export const BLOCK_LABELS: Record<BlockType, string> = {
  heading: 'Heading',
  paragraph: 'Paragraph',
  kv: 'Label and value rows',
  table: 'Table of a list',
  totals: 'Totals',
  spacer: 'Space',
  rule: 'Line',
  page_break: 'Page break',
  image: 'Image (logo)',
  signature: 'Signature line',
  qr: 'QR code',
}

export function newBlock(type: BlockType): Block {
  switch (type) {
    case 'heading':
      return { type, text: 'Title', level: 1 }
    case 'paragraph':
      return { type, text: 'Text with {{placeholders}}' }
    case 'kv':
      return { type, rows: [{ label: 'Label', value: '{{value}}' }] }
    case 'table':
      return { type, source: 'items', columns: [{ header: 'Item', value: '{{item.name}}', align: 'left', width: 4 }] }
    case 'totals':
      return { type, rows: [{ label: 'Total', value: '{{totals.total | money:@currency}}' }] }
    case 'spacer':
      return { type, height_mm: 8 }
    case 'signature':
      return { type, text: 'Signature' }
    case 'qr':
      return { type, value: '{{number}}', size_mm: 28 }
    case 'image':
      return { type, data_base64: '', width_mm: 40, align: 'left' }
    default:
      return { type }
  }
}

const SEP = ' :: '

/** rows <-> "label :: value" lines (a single `|` inside a placeholder is fine). */
export function rowsToText(rows: unknown): string {
  return (Array.isArray(rows) ? rows : []).map((r: { label?: string; value?: string }) => `${r.label ?? ''}${SEP}${r.value ?? ''}`).join('\n')
}

export function textToRows(text: string): { label: string; value: string }[] {
  return text
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((line) => {
      const i = line.indexOf(SEP)
      return i < 0 ? { label: line.trim(), value: '' } : { label: line.slice(0, i).trim(), value: line.slice(i + SEP.length).trim() }
    })
}

/** columns <-> "header :: value :: align :: width" lines. */
export function columnsToText(cols: unknown): string {
  return (Array.isArray(cols) ? cols : [])
    .map((c: { header?: string; value?: string; align?: string; width?: number }) => [c.header ?? '', c.value ?? '', c.align ?? 'left', String(c.width ?? 1)].join(SEP))
    .join('\n')
}

export function textToColumns(text: string): { header: string; value: string; align: string; width: number }[] {
  return text
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((line) => {
      const [header = '', value = '', align = 'left', width = '1'] = line.split(SEP).map((p) => p.trim())
      return { header, value, align: ['left', 'right', 'center'].includes(align) ? align : 'left', width: Number(width) > 0 ? Number(width) : 1 }
    })
}

export const RESERVED_ROLE_HINT = 'An empty list means nobody may render the template.'
