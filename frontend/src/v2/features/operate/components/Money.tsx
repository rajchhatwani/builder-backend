import { defaultExponent, formatMinor } from '../../../../shell/money/moneyLogic'
import type { Minor } from '../../../../shell/money/moneyLogic'
import { useT } from '../../../i18n'
import { SectionLink } from './Common'
import { data, key } from './Runtime'

export function useMoney() {
  const t = useT()
  return (amount: Minor, currency: string, exponent = defaultExponent(currency)) => data(t, currency + ' ' + formatMinor(amount, exponent))
}
export function LedgerLink({ projectId, id, label = 'ledgerTransaction' }: { projectId: string; id: string; label?: string }) {
  const t = useT()
  return <SectionLink id={projectId} section="ledger" label={t(key(label))} search={{ view: id }} />
}
