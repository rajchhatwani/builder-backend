import { useEffect, useState } from 'react'
import { useT } from '../../../i18n'
import { Button, useToast } from '../../../ui'

export function CopyButton({ value, label }: { value: string; label: string }) {
  const t = useT()
  const toast = useToast()
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(timer)
  }, [copied])
  return <Button onClick={async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
    } catch {
      toast({ title: t('connect.copyError'), tone: 'danger' })
    }
  }}>{copied ? t('connect.copied') : label}</Button>
}
