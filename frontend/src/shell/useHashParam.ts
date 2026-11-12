import { useEffect, useState } from 'react'

/** One `?name=value` pair inside the route hash (#/p/<id>/<section>?name=value); null when absent. Pure. */
export function hashParam(hash: string, name: string): string | null {
  const q = hash.indexOf('?')
  if (q < 0) return null
  const v = new URLSearchParams(hash.slice(q + 1)).get(name)
  return v === null || v === '' ? null : v
}

/** The same hash with `name` set (or removed when value is null). Pure. */
export function withHashParam(hash: string, name: string, value: string | null): string {
  const q = hash.indexOf('?')
  const base = q < 0 ? hash : hash.slice(0, q)
  const params = new URLSearchParams(q < 0 ? '' : hash.slice(q + 1))
  if (value === null) params.delete(name)
  else params.set(name, value)
  const s = params.toString()
  return s ? `${base}?${s}` : base
}

/** Live `?name=` of the current hash (updates on hashchange). */
export function useHashParam(name: string): string | null {
  const [v, setV] = useState(() => hashParam(window.location.hash, name))
  useEffect(() => {
    const on = () => setV(hashParam(window.location.hash, name))
    on()
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [name])
  return v
}
