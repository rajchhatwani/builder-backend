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
