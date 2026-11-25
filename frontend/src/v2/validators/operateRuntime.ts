import { parseMajor, validSeller, MAX_SAFE } from '../../shell/money/moneyLogic'

const issue = (code: string, values?: Record<string, string | number>) => ({ key: 'runtime.' + code, values })
export const currencyIssue = (value: string) => /^[A-Za-z]{3}$/.test(value.trim()) ? undefined : issue('currencyError')
export const accountCodeIssue = (value: string) => /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value.trim()) ? undefined : issue('accountCodeError')
export const sellerIssue = (value: string) => validSeller(value.trim()) ? undefined : issue('sellerError')
export const idempotencyIssue = (value: string) => /^(invoice|payment|payout):/.test(value.trim()) ? issue('reservedKey') : undefined
export function amountIssue(value: string, exponent: number, nonzero = false, limit = MAX_SAFE) {
  const minor = parseMajor(value, exponent)
  if (minor === null) return issue('amountFormat', { exponent })
  if (nonzero && minor === 0n) return issue('amountPositive')
  if (minor > limit) return issue('amountLimit')
}
export function wholeIssue(value: string, min: number, max: number) {
  const n = Number(value)
  if (!/^\d+$/.test(value.trim()) || n < min || n > max) return issue('wholeError', { min, max })
}

export const subjectIssue = (value: string) => /[\/\u0000]/.test(value) ? issue('subjectError') : undefined
export function geographicIssue(value: string, max: number) {
  const text = value.trim()
  if (!/^-?\d+(?:\.\d{1,6})?$/.test(text) || Math.abs(Number(text)) > max) return issue('coordinateError', { max })
}

export const noNullIssue = (value: string) => value.includes('\0') ? issue('nullCharacter') : undefined
export const uuidIssue = (value: string) => /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value.trim()) ? undefined : issue('uuidError')
export const signedWholeIssue = (value: string) => /^-?\d+$/.test(value.trim()) && Math.abs(Number(value)) <= 2 ** 53 ? undefined : issue('actualError')
export function departureIssue(value: string) {
  if (value && (!Number.isFinite(Date.parse(value)) || Math.abs(Date.parse(value) - Date.now()) > 3650 * 86400_000)) return issue('departureError')
}

export function readJsonObject(value: string): Record<string, unknown> | undefined {
  try {
    const object = JSON.parse(value) as unknown
    return object && typeof object === 'object' && !Array.isArray(object) ? object as Record<string, unknown> : undefined
  } catch {
    return undefined
  }
}
export const jsonObjectIssue = (value: string) => readJsonObject(value) === undefined ? issue('jsonObjectError') : undefined

export const pdfRateIssue = (value: string) => /^[1-9][0-9]{0,5}\/([1-9][0-9]{0,2})?(second|minute|hour|day)s?$/.test(value) ? undefined : issue('pdfRateError')
export const pdfIdIssue = (value: string) => /^[a-z][a-z0-9_]{0,39}$/.test(value) ? undefined : issue('pdfIdError')
export const pdfComputeIssue = (value: string) => !value || /^[A-Za-z_][A-Za-z0-9_]*$/.test(value) ? undefined : issue('pdfComputeError')
export function pdfPreviewIssue(blocks: Record<string, unknown>[], data: Record<string, unknown>) {
  const cells = blocks.reduce((total, block) => {
    if (block.type !== 'table' || !Array.isArray(block.columns) || typeof block.source !== 'string') return total
    const items = block.source.split('.').reduce<unknown>((value, key) =>
      value && typeof value === 'object' && Object.hasOwn(value, key) ? (value as Record<string, unknown>)[key] : undefined, data)
    return total + block.columns.length * Math.max(1, Array.isArray(items) ? items.length : 0)
  }, 0)
  return cells > 20_000 ? issue('pdfCellsError') : undefined
}
