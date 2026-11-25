import { useId, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { useT } from '../i18n'
import { Button, Input, Row, Sheet, Stack } from '../ui'

export type Command = { id: string; label: string; hint: string; run: () => void }

export function CommandPalette({ open, onOpenChange, commands, label, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void; commands: Command[]; label: string
  returnFocus?: RefObject<HTMLElement | null>
}) {
  const t = useT()
  return <Sheet title={label} returnFocus={returnFocus} trigger={!returnFocus ? <Button aria-keyshortcuts="Control+K Meta+K">
    <span>{label}</span><kbd aria-hidden className="v2-phone-hidden">{t('command.shortcut')}</kbd>
  </Button> : undefined} open={open} onOpenChange={onOpenChange}>
    {open && <CommandSearch commands={commands} close={() => onOpenChange(false)} />}
  </Sheet>
}

function CommandSearch({ commands, close }: { commands: Command[]; close: () => void }) {
  const t = useT()
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const list = useId()
  const selected = useRef<HTMLLIElement>(null)
  const words = query.trim().toLocaleLowerCase().split(/\s+/)
  const rows = commands.filter(({ label, hint }) => words.every(word => (label + ' ' + hint).toLocaleLowerCase().includes(word)))
  const active = Math.min(index, rows.length - 1)
  function run(row: Command | undefined) {
    if (!row) return
    close()
    row.run()
  }

  return (
    <Stack>
      <Input role="combobox" aria-label={t('command.search')} aria-autocomplete="list" aria-expanded={rows.length > 0} aria-controls={list}
        aria-activedescendant={active >= 0 ? list + '-' + active : undefined} value={query}
        placeholder={t('command.placeholder')} onChange={event => { setQuery(event.target.value); setIndex(0) }}
        onKeyDown={event => {
          if (event.key === 'Enter') { event.preventDefault(); run(rows[active]); return }
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
          event.preventDefault()
          const next = Math.max(0, Math.min(active + (event.key === 'ArrowDown' ? 1 : -1), rows.length - 1))
          setIndex(next)
          requestAnimationFrame(() => selected.current?.scrollIntoView?.({ block: 'nearest' }))
        }} />
      <ul hidden={!rows.length} id={list} className="v2-command-list" role="listbox" aria-label={t('command.options')}>
        {rows.map((row, i) => <li key={row.id} id={list + '-' + i} role="option" aria-selected={i === active}
          ref={i === active ? selected : undefined} onMouseMove={() => setIndex(i)}
          onMouseDown={event => event.preventDefault()} onClick={() => run(row)}>
          <Row className="v2-spread">{row.label}<span className="v2-muted">{row.hint}</span></Row>
        </li>)}
      </ul>
      {!rows.length && <p role="status">{t('command.empty')}</p>}
    </Stack>
  )
}
