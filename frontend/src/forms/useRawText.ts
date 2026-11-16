import { useState } from 'react'

/**
 * Text the user is typing for a parsed value. The raw text is kept while it still parses to the value
 * held by the parent, so commas, spaces and separators survive each keystroke; when the parent value
 * changes some other way the text is rebuilt from it.
 */
export function shownText<T>(text: string, value: T, parse: (t: string) => T, toText: (v: T) => string): string {
  return JSON.stringify(parse(text)) === JSON.stringify(value) ? text : toText(value)
}

export function useRawText<T>(value: T, parse: (t: string) => T, toText: (v: T) => string): [string, (t: string) => void] {
  const [text, setText] = useState(() => toText(value))
  return [shownText(text, value, parse, toText), setText]
}
