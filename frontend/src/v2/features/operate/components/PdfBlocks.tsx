import { useEffect, useRef, useState } from 'react'
import { useT } from '../../../i18n'
import { ConfirmDestructive } from '../../../patterns'
import { Alert, Button, Disclosure, Field, Grid, Input, Row, Stack, Textarea } from '../../../ui'
import { BLOCK_LABELS, columnsToText, newBlock, rowsToText, textToColumns, textToRows } from '../../../../components/documents/blocks'
import type { BlockType } from '../../../../components/documents/blocks'
import { key, Pick } from './Runtime'

const types = Object.keys(BLOCK_LABELS) as BlockType[]
type Block = Record<string, unknown>
export function PdfBlocks({ blocks, disabled, onChange }: { blocks: Block[]; disabled: boolean; onChange: (blocks: Block[]) => void }) {
  const t = useT()
  const [type, setType] = useState<BlockType>('heading')
  function move(from: number, to: number) {
    const next = [...blocks]
    const [block] = next.splice(from, 1)
    next.splice(to, 0, block)
    onChange(next)
  }
  return <Stack>
    <h3>{t(key('pdfContent'))}</h3>
    {blocks.map((block, index) => <Disclosure key={index + ':' + String(block.type)} label={t(key('blockHeading'), {
      number: index + 1, name: t(key('block.' + String(block.type))),
    })}>
      <Stack>
        <BlockFields block={block} disabled={disabled} onChange={patch => onChange(blocks.map((item, i) => i === index ? { ...item, ...patch } : item))} />
        {!disabled && <Row>
          <Button disabled={index === 0} onClick={() => move(index, index - 1)}>{t(key('up'))}</Button>
          <Button disabled={index === blocks.length - 1} onClick={() => move(index, index + 1)}>{t(key('down'))}</Button>
          <ConfirmDestructive trigger={<Button variant="danger">{t(key('remove'))}</Button>}
            title={t(key('removeBlock'))} description={t(key('removeBlockHelp'))} action={t(key('remove'))}
            onConfirm={() => onChange(blocks.filter((_, i) => index !== i))} />
        </Row>}
      </Stack>
    </Disclosure>)}
    {!disabled && <Row>
      <Pick label={t(key('blockType'))} value={type} options={types.map(value => ({ value, label: t(key('block.' + value)) }))}
        onChange={value => setType(value as BlockType)} />
      <Button disabled={blocks.length >= 200} onClick={() => onChange([...blocks, newBlock(type)])}>{t(key('addBlock'))}</Button>
    </Row>}
  </Stack>
}

function ParsedLines({ label, initial, disabled, onChange }: { label: string; initial: string; disabled: boolean; onChange: (value: string) => string }) {
  const t = useT()
  const [draft, setDraft] = useState(initial)
  const recent = useRef(initial)
  const value = recent.current === initial ? draft : initial
  return <Field label={t(key(label))}>{attrs => <Textarea {...attrs} value={value} disabled={disabled} onChange={event => {
    const next = event.target.value
    setDraft(next)
    recent.current = onChange(next)
  }} />}</Field>
}

function BlockFields({ block, disabled, onChange }: { block: Block; disabled: boolean; onChange: (patch: Block) => void }) {
  const t = useT()
  const string = (name: string, fallback = '') => typeof block[name] === 'string' ? String(block[name]) : fallback
  const textField = (name: string, label: string) => <Field label={t(key(label))}>{attrs => <Textarea {...attrs} value={string(name)}
    disabled={disabled} onChange={event => onChange({ [name]: event.target.value })} />}</Field>
  const numberField = (name: string, label: string, fallback: number, min: number, max: number) =>
    <Field label={t(key(label))}>{attrs => <Input {...attrs} type="number" value={Number(block[name] ?? fallback)} min={min} max={max}
      disabled={disabled} onChange={event => {
        const value = event.target.valueAsNumber
        if (Number.isFinite(value)) onChange({ [name]: value })
      }} />}</Field>
  const select = (name: string, label: string, value: string, options: string[], numeric = false) => disabled ?
    <p>{t(key('labelValue'), { label: t(key(label)), value: t(key('blockOption.' + value)) })}</p> :
    <Pick label={t(key(label))} value={value} options={options.map(value => ({ value, label: t(key('blockOption.' + value)) }))}
      onChange={value => onChange({ [name]: numeric ? Number(value) : value })} />
  if (block.type === 'heading') return <Grid>{textField('text', 'blockText')}{select('level', 'blockSize', String(block.level ?? 1), ['1', '2', '3'], true)}</Grid>
  if (block.type === 'paragraph' || block.type === 'signature') return textField('text', 'blockText')
  if (block.type === 'kv' || block.type === 'totals') return <ParsedLines label={'blockRows'} initial={rowsToText(block.rows)} disabled={disabled}
    onChange={value => { const rows = textToRows(value); onChange({ rows }); return rowsToText(rows) }} />
  if (block.type === 'table') return <Stack>{textField('source', 'listName')}
    <ParsedLines label={'blockColumns'} initial={columnsToText(block.columns)} disabled={disabled}
      onChange={value => { const columns = textToColumns(value); onChange({ columns }); return columnsToText(columns) }} /></Stack>
  if (block.type === 'spacer') return numberField('height_mm', 'heightMm', 8, 1, 100)
  if (block.type === 'qr') return <Grid>{textField('value', 'qrContent')}{numberField('size_mm', 'sizeMm', 28, 10, 80)}</Grid>
  if (block.type === 'image') return <Grid>
    <BlockImage label={t(key('pdfImage'))} disabled={disabled} onChange={data_base64 => onChange({ data_base64 })} />
    {numberField('width_mm', 'widthMm', 40, 5, 180)}
    {select('align', 'alignment', string('align', 'left'), ['left', 'center', 'right'])}
  </Grid>
  return null
}

function BlockImage({ label, disabled, onChange }: { label: string; disabled: boolean; onChange: (value: string) => void }) {
  const t = useT()
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  const readerRef = useRef<FileReader>(null)
  const changeRef = useRef(onChange)
  useEffect(() => { changeRef.current = onChange }, [onChange])
  useEffect(() => () => {
    const reader = readerRef.current
    if (reader?.readyState === FileReader.LOADING) {
      reader.onloadend = null
      reader.abort()
    }
  }, [])
  return <Stack>
    <Field label={label}>{attrs => <Input {...attrs} type="file" accept="image/png,image/jpeg" disabled={disabled || loading} onChange={event => {
      const file = event.target.files?.[0]
      if (!file) return
      if (file.size > 200_000 || !['image/png', 'image/jpeg'].includes(file.type)) { setError(true); return }
      setError(false)
      setLoading(true)
      const reader = new FileReader()
      readerRef.current = reader
      reader.onload = () => changeRef.current(String(reader.result).split(',')[1] ?? '')
      reader.onerror = () => setError(true)
      reader.onloadend = () => setLoading(false)
      reader.readAsDataURL(file)
    }} />}</Field>
    {error && <Alert tone="danger">{t(key('pdfImageError'))}</Alert>}
  </Stack>
}
