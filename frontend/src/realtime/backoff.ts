export const BASE_MS = 1000
export const MAX_MS = 30_000
export const STABLE_MS = 10_000

/** Exponential backoff with +-25% jitter (rand in [0,1)); a Retry-After (seconds) is a floor, never undercut. */
export function reconnectDelay(attempt: number, retryAfterSec: number | null = null, rand: () => number = Math.random): number {
  const exp = Math.min(MAX_MS, BASE_MS * 2 ** Math.max(0, Math.min(attempt, 10)))
  const jittered = Math.round(exp * (0.75 + rand() * 0.5))
  const floor = retryAfterSec !== null && Number.isFinite(retryAfterSec) && retryAfterSec > 0 ? Math.min(retryAfterSec, 120) * 1000 : 0
  return Math.max(jittered, floor)
}

export function parseRetryAfter(value: string | null): number | null {
  if (!value || !/^\d{1,5}$/.test(value.trim())) return null
  return Number(value.trim())
}
