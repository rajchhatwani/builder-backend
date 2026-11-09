/** Pure, chunk-safe Server-Sent Events parser (WHATWG rules): lines end in \n, \r or \r\n, frames end at a blank line,
 *  lines starting with ":" are comments, repeated data lines join with \n, a leading BOM is dropped.
 *  Feed it decoded text in any split; it keeps the unfinished tail. */
export interface SseFrame {
  id?: string
  event: string
  data: string
  retry?: number
}

export interface SseParser {
  push(chunk: string): SseFrame[]
}

export function createSseParser(): SseParser {
  let tail = ''
  let first = true
  let id: string | undefined
  let event = ''
  let data: string[] = []
  let hasData = false
  let retry: number | undefined
  let lastWasCR = false

  const reset = () => {
    id = undefined
    event = ''
    data = []
    hasData = false
    retry = undefined
  }

  const line = (l: string, out: SseFrame[]) => {
    if (l === '') {
      if (hasData) out.push({ ...(id !== undefined ? { id } : {}), event: event || 'message', data: data.join('\n'), ...(retry !== undefined ? { retry } : {}) })
      reset()
      return
    }
    if (l.startsWith(':')) return
    const i = l.indexOf(':')
    const field = i === -1 ? l : l.slice(0, i)
    let value = i === -1 ? '' : l.slice(i + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'data') { data.push(value); hasData = true }
    else if (field === 'event') event = value
    else if (field === 'id') { if (!value.includes('\0')) id = value }
    else if (field === 'retry') { if (/^\d+$/.test(value)) retry = Number(value) }
  }

  return {
    push(chunk: string): SseFrame[] {
      let text = tail + chunk
      if (first && text.length > 0) {
        if (text.startsWith('﻿')) text = text.slice(1)
        first = false
      }
      // A "\n" right after a chunk-final "\r" is the second half of one "\r\n".
      if (lastWasCR && text.startsWith('\n')) text = text.slice(1)
      lastWasCR = false
      const out: SseFrame[] = []
      let start = 0
      let i = 0
      while (i < text.length) {
        const c = text[i]
        if (c === '\n' || c === '\r') {
          line(text.slice(start, i), out)
          if (c === '\r') {
            if (text[i + 1] === '\n') i++
            else if (i + 1 === text.length) lastWasCR = true
          }
          start = i + 1
        }
        i++
      }
      tail = text.slice(start)
      return out
    },
  }
}
