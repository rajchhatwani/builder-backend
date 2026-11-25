// The generated scheduler uses the strict five-field grammar in app/core/jobs_cron.py.
const bounds = [[0, 59], [0, 23], [1, 31], [1, 12], [0, 6]]
const minuteMs = 60_000
const dayMs = 24 * 60 * minuteMs

function field(text: string, low: number, high: number) {
  const values = new Set<number>()
  for (const item of text.split(',')) {
    const match = /^(\*|\d{1,2}(?:-\d{1,2})?)(?:\/(\d{1,2}))?$/.exec(item)
    if (!match) return
    const [, range, stride] = match
    const [start, end = start] = range === '*' ? [low, high] : range.split('-').map(Number)
    const step = stride ? Number(stride) : 1
    if (start < low || end > high || end < start || step < 1 || step > high - low + 1 ||
      (stride && range !== '*' && !range.includes('-'))) return
    for (let value = start; value <= end; value += step) values.add(value)
  }
  return [...values].sort((a, b) => a - b)
}

export function upcomingTimes(cron: string, timeZone: string, now: number): number[] | undefined {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== bounds.length) return
  const parsed = bounds.map(([low, high], i) => field(parts[i], low, high))
  if (parsed.some(values => !values)) return
  const [minutes, hours, dates, months, weekdays] = parsed as number[][]
  let format: Intl.DateTimeFormat
  try {
    format = new Intl.DateTimeFormat('en', {
      timeZone, year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23',
    })
  } catch {
    return
  }
  const localTime = (time: number) => {
    const values = Object.fromEntries(format.formatToParts(time).map(part => [part.type, Number(part.value)]))
    return Date.UTC(values.year, values.month - 1, values.day, values.hour, values.minute)
  }
  const minute = Math.floor(now / minuteMs) * minuteMs
  const today = Math.floor(localTime(minute) / dayMs) * dayMs
  const results: number[] = []
  for (let day = today; day <= today + 14 * dayMs && results.length < 5; day += dayMs) {
    const date = new Date(day)
    const dom = dates.includes(date.getUTCDate())
    const dow = weekdays.includes(date.getUTCDay())
    const eligible = parts[2] !== '*' && parts[4] !== '*' ? dom || dow : dom && dow
    if (!eligible || !months.includes(date.getUTCMonth() + 1)) continue
    const offsets = [...new Set([-1, 0, 1, 2].map(step => {
      const sample = day + step * dayMs
      return localTime(sample) - sample
    }))].sort((a, b) => b - a)

    for (const hour of hours) {
      for (const mins of minutes) {
        const local = day + (hour * 60 + mins) * minuteMs
        // A repeated wall time runs at its first occurrence. A skipped wall time has no candidate.
        const first = offsets.map(offset => local - offset).find(candidate => localTime(candidate) === local)
        if (first !== undefined && first > now && first <= now + 14 * dayMs) results.push(first)
        if (results.length === 5) return results
      }
    }
  }
  return results
}
