import type { Path } from '../../forms/schemaLogic'

export function changeSchemaValue(value: unknown, path: Path, next: unknown): unknown {
  if (!path.length) return next
  const [head, ...rest] = path
  if (typeof head === 'number') {
    const items = Array.isArray(value) ? value : []
    return items.map((item, index) => index === head ? changeSchemaValue(item, rest, next) : item)
  }
  const object = value as Record<string, unknown> | undefined
  return { ...object, [head]: changeSchemaValue(object?.[head], rest, next) }
}
