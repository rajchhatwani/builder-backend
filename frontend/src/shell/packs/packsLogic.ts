/** Pure helpers for editing ONE sub-block of the `packs` spec object without touching anything else. */
export type Obj = Record<string, unknown>
const isObj = (x: unknown): x is Obj => x !== null && typeof x === 'object' && !Array.isArray(x)

/** The block at packs[pack][block] (or packs[pack] when `block` is undefined); null when off. */
export function getBlock(packs: Obj | null | undefined, pack: string, block?: string): Obj | null {
  const p = packs?.[pack]
  if (!isObj(p)) return null
  if (!block) return p
  const b = p[block]
  return isObj(b) ? b : null
}

/** A copy of `packs` with the block replaced. All other packs and sibling blocks are kept as they are. */
export function setBlock(packs: Obj | null | undefined, pack: string, block: string | undefined, value: Obj): Obj {
  const base = packs ?? {}
  if (!block) return { ...base, [pack]: value }
  const p = isObj(base[pack]) ? (base[pack] as Obj) : {}
  return { ...base, [pack]: { ...p, [block]: value } }
}

/** A copy of `packs` with the block removed; a pack left without any block is removed too. */
export function removeBlock(packs: Obj | null | undefined, pack: string, block?: string): Obj {
  const { [pack]: p, ...rest } = packs ?? {}
  if (!block || !isObj(p)) return rest
  const { [block]: _gone, ...siblings } = p
  return Object.keys(siblings).length ? { ...rest, [pack]: siblings } : rest
}
