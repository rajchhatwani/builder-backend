import { useRawText } from '../forms/useRawText'

/** A textarea whose text is parsed into a value on every change but is not rewritten while it still matches. */
export function ParsedTextarea<T>({ value, parse, toText, onChange, rows }: { value: T; parse: (t: string) => T; toText: (v: T) => string; onChange: (v: T) => void; rows: number }) {
  const [text, setText] = useRawText(value, parse, toText)
  return (
    <textarea
      rows={rows}
      value={text}
      onChange={(e) => {
        setText(e.target.value)
        onChange(parse(e.target.value))
      }}
    />
  )
}
