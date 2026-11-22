import { useRawText } from '../../forms/useRawText'
import { Field } from '../behavior/ui'
import { listText, parseList } from './platformLogic'

/** Comma-separated list input: keeps the raw text while it still parses to the held list. */
export function ListInput({ id, label, value, onChange, disabled, messages, hint }: {
  id: string; label: string; value: string[]; onChange: (v: string[]) => void; disabled: boolean; messages?: string[]; hint?: string
}) {
  const [text, setText] = useRawText(value, parseList, listText)
  return (
    <Field id={id} label={label} messages={messages} hint={hint}>
      {(p) => <input {...p} value={text} disabled={disabled} onChange={(e) => { setText(e.target.value); onChange(parseList(e.target.value)) }} />}
    </Field>
  )
}
