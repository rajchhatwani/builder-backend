import type { JsonSchema } from '../../forms'
import ledger from '../../forms/schemas/ledger.json'
import currency from '../../forms/schemas/currency.json'
import recon from '../../forms/schemas/reconciliation.json'
import invoicing from '../../forms/schemas/invoicing.json'
import booking from '../../forms/schemas/booking-pack.json'
import { PackFormPage } from './PackFormPage'

type P = { projectId: string }

export const LedgerSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="money" block="ledger" title="Ledger settings" schema={ledger as JsonSchema}
    intro="Double-entry ledger: who may read and post, and the size limits of one entry. Amounts are integer minor units." />
)
export const CurrencySettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="money" block="currency" title="Currency settings" schema={currency as JsonSchema}
    intro="Currencies, rounding and optional static tax rates (basis points)." />
)
export const ReconSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="money" block="reconciliation" title="Reconciliation settings" schema={recon as JsonSchema}
    intro="Who may read and run statement reconciliation, the matching tolerance and the statement size cap." />
)
export const InvoicingSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="money" block="invoicing" title="Invoicing settings" schema={invoicing as JsonSchema}
    intro="Invoice numbering, payment terms, ledger accounts, aging buckets and optional payouts." />
)
export const BookingSettingsPage = ({ projectId }: P) => (
  <PackFormPage projectId={projectId} pack="booking" title="Booking settings" schema={booking as JsonSchema}
    intro="Bookable kinds (slots, ranges, pools), hold time, horizon, cancellation and who may read, book and manage." />
)
