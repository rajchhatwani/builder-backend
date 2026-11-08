import { useUi } from './Ui'

/** A labelled value with a Copy button (SSO details, DNS records, SCIM URLs and token). */
export function Copyable({ label, value }: { label: string; value: string }) {
  const { toast } = useUi()
  return (
    <div className="copy-row">
      <span className="small-text muted">{label}</span>
      <code className="small-text">{value}</code>
      <button type="button" className="ghost small" onClick={() => navigator.clipboard.writeText(value).then(() => toast('Copied.'))}>
        Copy
      </button>
    </div>
  )
}
