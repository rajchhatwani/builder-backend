import { useId, useMemo, useState } from 'react'
import { Modal } from '../components/Modal'
import { filterCommands, type Command } from './groups'

interface Props {
  commands: Command[]
  onClose: () => void
}

/** Ctrl+K palette: type to filter, arrows to move, Enter to run, Esc to close. Mounted only while open. */
export function CommandPalette({ commands, onClose }: Props) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listId = useId()
  const shown = useMemo(() => filterCommands(commands, query), [commands, query])
  const current = Math.min(active, Math.max(shown.length - 1, 0))

  function run(cmd: Command | undefined) {
    if (!cmd) return
    onClose()
    cmd.run()
  }

  return (
    <Modal open onClose={onClose}>
      <form method="dialog" className="palette" onSubmit={(e) => e.preventDefault()}>
        <header>
          <input
            role="combobox"
            aria-label="Search commands"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={shown.length ? `${listId}-${current}` : undefined}
            placeholder="Jump to a page or run a command"
            autoComplete="off"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive(Math.min(current + 1, shown.length - 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive(Math.max(current - 1, 0))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                run(shown[current])
              }
            }}
          />
        </header>
        <div>
          <ul id={listId} role="listbox" aria-label="Commands" className="palette-list">
            {shown.map((c, i) => (
              <li
                key={c.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === current}
                onMouseMove={() => active !== i && setActive(i)}
                onClick={() => run(c)}
              >
                <span>{c.label}</span>
                <span className="muted small-text">{c.hint}</span>
              </li>
            ))}
          </ul>
          {!shown.length && <p className="muted">No match.</p>}
        </div>
      </form>
    </Modal>
  )
}
